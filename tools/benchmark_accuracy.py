import argparse
import statistics
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from analysis_service import (  # noqa: E402
    analyze_move,
    analyze_rows_parallel,
    open_stockfish,
)
from database import connect  # noqa: E402


def load_rows(username, provider, game_limit):
    with connect() as conn:
        game_ids = [
            row["id"]
            for row in conn.execute(
                """
                SELECT id
                FROM games
                WHERE provider = ? AND lower(player_username) = lower(?)
                ORDER BY replace(date, '.', '-') DESC, id DESC
                LIMIT ?
                """,
                (provider, username, game_limit),
            ).fetchall()
        ]
        placeholders = ",".join("?" for _ in game_ids)
        rows = conn.execute(
            f"""
            SELECT m.id, m.game_id, m.ply, m.fen_before, m.fen_after, m.move
            FROM moves m
            WHERE m.game_id IN ({placeholders})
            ORDER BY m.game_id, m.ply
            """,
            game_ids,
        ).fetchall()
        job = conn.execute(
            "SELECT id FROM analysis_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return rows, job["id"] if job else -1


def run_sequential(rows, depth):
    engine = open_stockfish(threads=1, hash_mb=64)
    started = time.perf_counter()
    try:
        results = {
            row["id"]: analyze_move(engine, row["fen_before"], row["move"], depth)
            for row in rows
        }
    finally:
        engine.quit()
    return results, time.perf_counter() - started


def run_parallel(rows, depth, workers, job_id):
    started = time.perf_counter()
    results = {
        move_id: (best_move, diff, classification)
        for move_id, best_move, diff, classification in analyze_rows_parallel(
            rows,
            depth,
            workers,
            job_id,
        )
    }
    return results, time.perf_counter() - started


def compare(candidate, reference):
    ids = sorted(set(candidate) & set(reference))
    best_matches = 0
    class_matches = 0
    errors = []
    threshold_changes = 0
    severe_changes = 0

    severity = {
        "best": 0,
        "inaccuracy": 1,
        "mistake": 2,
        "blunder": 3,
        "unknown": 4,
        "illegal": 4,
    }

    for move_id in ids:
        candidate_best, candidate_diff, candidate_class = candidate[move_id]
        reference_best, reference_diff, reference_class = reference[move_id]
        best_matches += candidate_best == reference_best
        class_matches += candidate_class == reference_class
        if candidate_diff is not None and reference_diff is not None:
            errors.append(abs(candidate_diff - reference_diff))
        gap = abs(
            severity.get(candidate_class, 4) - severity.get(reference_class, 4)
        )
        threshold_changes += gap > 0
        severe_changes += gap >= 2

    return {
        "moves": len(ids),
        "best_move_match": best_matches / len(ids) * 100,
        "classification_match": class_matches / len(ids) * 100,
        "mean_abs_eval_error": statistics.mean(errors),
        "median_abs_eval_error": statistics.median(errors),
        "p95_abs_eval_error": sorted(errors)[int((len(errors) - 1) * 0.95)],
        "classification_changes": threshold_changes,
        "severe_classification_changes": severe_changes,
    }


def print_result(label, elapsed, metrics):
    print(
        f"{label} seconds={elapsed:.3f} "
        f"best_move_match={metrics['best_move_match']:.2f}% "
        f"classification_match={metrics['classification_match']:.2f}% "
        f"mean_abs_eval_error={metrics['mean_abs_eval_error']:.1f}cp "
        f"median_abs_eval_error={metrics['median_abs_eval_error']:.1f}cp "
        f"p95_abs_eval_error={metrics['p95_abs_eval_error']:.1f}cp "
        f"classification_changes={metrics['classification_changes']} "
        f"severe_changes={metrics['severe_classification_changes']}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="Nelo_w")
    parser.add_argument("--provider", default="lichess")
    parser.add_argument("--games", type=int, default=6)
    parser.add_argument("--candidate-depth", type=int, default=14)
    parser.add_argument("--reference-depth", type=int, default=16)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--reference-workers", type=int)
    args = parser.parse_args()
    reference_workers = args.reference_workers or args.workers

    rows, job_id = load_rows(args.username, args.provider, args.games)
    print(
        f"moves={len(rows)} candidate_depth={args.candidate_depth} "
        f"reference_depth={args.reference_depth} workers={args.workers} "
        f"reference_workers={reference_workers}"
    )

    reference, reference_seconds = run_parallel(
        rows,
        args.reference_depth,
        reference_workers,
        job_id,
    )
    sequential, sequential_seconds = run_sequential(rows, args.candidate_depth)
    parallel, parallel_seconds = run_parallel(
        rows,
        args.candidate_depth,
        args.workers,
        job_id,
    )

    print(f"reference_seconds={reference_seconds:.3f}")
    print_result(
        "sequential",
        sequential_seconds,
        compare(sequential, reference),
    )
    print_result(
        "parallel",
        parallel_seconds,
        compare(parallel, reference),
    )
    direct = compare(parallel, sequential)
    print_result("parallel_vs_sequential", parallel_seconds, direct)


if __name__ == "__main__":
    main()
