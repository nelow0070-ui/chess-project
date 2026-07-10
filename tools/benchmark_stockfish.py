import argparse
import queue
import sqlite3
import sys
import threading
import time
from pathlib import Path

import chess
import chess.engine


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from config import DB_PATH, STOCKFISH_PATH, STOCKFISH_POPEN_ARGS  # noqa: E402


def load_positions(username, provider, game_limit):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        games = conn.execute(
            """
            SELECT id
            FROM games
            WHERE provider = ? AND lower(player_username) = lower(?)
            ORDER BY replace(date, '.', '-') DESC, id DESC
            LIMIT ?
            """,
            (provider, username, game_limit),
        ).fetchall()
        game_ids = [row["id"] for row in games]
        if not game_ids:
            raise RuntimeError("No matching games were found.")
        placeholders = ",".join("?" for _ in game_ids)
        moves = conn.execute(
            f"""
            SELECT game_id, ply, fen_before, fen_after
            FROM moves
            WHERE game_id IN ({placeholders})
            ORDER BY game_id, ply
            """,
            game_ids,
        ).fetchall()

    duplicate_positions = []
    unique_positions = []
    seen = set()
    for move in moves:
        for fen in (move["fen_before"], move["fen_after"]):
            duplicate_positions.append(fen)
            if fen not in seen:
                seen.add(fen)
                unique_positions.append(fen)
    return len(game_ids), len(moves), duplicate_positions, unique_positions


def analyze_positions(positions, depth, workers, threads, hash_mb, engine_path):
    work = queue.Queue()
    for fen in positions:
        work.put(fen)

    totals = {"positions": 0, "nodes": 0}
    totals_lock = threading.Lock()
    errors = []

    def run_worker():
        engine = None
        local_positions = 0
        local_nodes = 0
        try:
            engine = chess.engine.SimpleEngine.popen_uci(
                engine_path,
                **STOCKFISH_POPEN_ARGS,
            )
            engine.configure({"Threads": threads, "Hash": hash_mb})
            while True:
                try:
                    fen = work.get_nowait()
                except queue.Empty:
                    break
                info = engine.analyse(
                    chess.Board(fen),
                    chess.engine.Limit(depth=depth),
                    info=chess.engine.INFO_SCORE | chess.engine.INFO_BASIC,
                )
                local_positions += 1
                local_nodes += int(info.get("nodes") or 0)
        except Exception as exc:
            errors.append(exc)
        finally:
            if engine is not None:
                try:
                    engine.quit()
                except Exception:
                    pass
            with totals_lock:
                totals["positions"] += local_positions
                totals["nodes"] += local_nodes

    started = time.perf_counter()
    threads_list = [
        threading.Thread(target=run_worker, name=f"stockfish-bench-{index}")
        for index in range(workers)
    ]
    for worker in threads_list:
        worker.start()
    for worker in threads_list:
        worker.join()
    elapsed = time.perf_counter() - started

    if errors:
        raise errors[0]
    if totals["positions"] != len(positions):
        raise RuntimeError(
            f"Expected {len(positions)} positions, analyzed {totals['positions']}."
        )
    return {
        "seconds": elapsed,
        "positions_per_second": len(positions) / elapsed,
        "nodes": totals["nodes"],
        "nodes_per_second": totals["nodes"] / elapsed,
    }


def parse_config(value):
    workers, threads = value.lower().split("x", 1)
    return int(workers), int(threads)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="Nelo_w")
    parser.add_argument("--provider", default="lichess")
    parser.add_argument("--games", type=int, default=6)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--hash", type=int, default=64)
    parser.add_argument("--engine", default=STOCKFISH_PATH)
    parser.add_argument(
        "--configs",
        nargs="+",
        default=["1x1", "1x4", "2x2", "4x1", "4x2", "6x1", "6x2", "8x1"],
        help="Worker count x Stockfish threads per worker.",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Also benchmark the current duplicate-position approach with 1x1.",
    )
    args = parser.parse_args()

    game_count, move_count, duplicate_positions, unique_positions = load_positions(
        args.username,
        args.provider,
        args.games,
    )
    print(
        f"games={game_count} moves={move_count} "
        f"duplicate_positions={len(duplicate_positions)} "
        f"unique_positions={len(unique_positions)} depth={args.depth} "
        f"engine={args.engine}"
    )

    if args.baseline:
        result = analyze_positions(
            duplicate_positions,
            args.depth,
            workers=1,
            threads=1,
            hash_mb=args.hash,
            engine_path=args.engine,
        )
        print(
            "mode=duplicate config=1x1 "
            f"seconds={result['seconds']:.3f} "
            f"positions_per_second={result['positions_per_second']:.2f} "
            f"nodes_per_second={result['nodes_per_second']:.0f}"
        )

    for config in args.configs:
        workers, engine_threads = parse_config(config)
        result = analyze_positions(
            unique_positions,
            args.depth,
            workers=workers,
            threads=engine_threads,
            hash_mb=args.hash,
            engine_path=args.engine,
        )
        print(
            f"mode=unique config={config} "
            f"cpu_threads={workers * engine_threads} "
            f"seconds={result['seconds']:.3f} "
            f"positions_per_second={result['positions_per_second']:.2f} "
            f"nodes_per_second={result['nodes_per_second']:.0f}"
        )


if __name__ == "__main__":
    main()
