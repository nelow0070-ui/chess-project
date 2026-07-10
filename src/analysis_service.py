import json
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import chess
import chess.engine

from config import (
    DEFAULT_ANALYSIS_DEPTH,
    DEFAULT_ANALYSIS_WORKERS,
    STOCKFISH_FALLBACK_PATHS,
    STOCKFISH_HASH_MB,
    STOCKFISH_PATH,
    STOCKFISH_POPEN_ARGS,
)
from database import connect, utc_now


STATUS_LABELS = {
    "queued": "대기 중",
    "running": "분석 중",
    "cancelled": "중단됨",
    "completed": "완료",
    "failed": "실패",
}
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 10000,
}

DEPTH_SECONDS = {
    8: 0.005,
    10: 0.015,
    12: 0.043,
    14: 0.18,
    16: 0.75,
}
ANALYSIS_CHUNK_SIZE = 2000
DATABASE_WRITE_BATCH_SIZE = 25


def score_cp(score):
    if score is None:
        return None
    if score.is_mate():
        mate = score.mate()
        return 10000 if mate and mate > 0 else -10000
    return score.score()


def classify(diff):
    if diff is None:
        return "unknown"
    if diff < 50:
        return "best"
    if diff < 150:
        return "inaccuracy"
    if diff < 300:
        return "mistake"
    return "blunder"


def material_for(board, color):
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        if piece_type == chess.KING:
            continue
        total += len(board.pieces(piece_type, color)) * value
    return total


def material_balance(board, color):
    return material_for(board, color) - material_for(board, not color)


def is_piece_sacrifice(before_board, move):
    piece = before_board.piece_at(move.from_square)
    if not piece or piece.piece_type in {chess.PAWN, chess.KING}:
        return False

    after_board = before_board.copy(stack=False)
    before_balance = material_balance(before_board, piece.color)
    try:
        after_board.push(move)
    except AssertionError:
        return False
    after_balance = material_balance(after_board, piece.color)
    if after_balance <= before_balance - 200:
        return True

    moved_value = PIECE_VALUES[piece.piece_type]
    for reply in after_board.legal_moves:
        if reply.to_square != move.to_square:
            continue
        attacker = after_board.piece_at(reply.from_square)
        if not attacker:
            continue
        if PIECE_VALUES[attacker.piece_type] <= moved_value:
            return True
    return False


def classify_move(diff, before_board=None, move=None, before_score=None, after_score=None):
    if (
        diff is not None
        and diff <= 80
        and before_board is not None
        and move is not None
        and before_score is not None
        and after_score is not None
        and before_score < 500
        and after_score >= -100
        and is_piece_sacrifice(before_board, move)
    ):
        return "brilliant"
    return classify(diff)


def analyze_move(engine, fen, move_uci, depth):
    board = chess.Board(fen)
    mover = board.turn
    limit = chess.engine.Limit(depth=depth)
    before = engine.analyse(board, limit)
    best_move = before.get("pv", [None])[0]
    before_score = score_cp(before["score"].relative)

    move = chess.Move.from_uci(move_uci)
    if move not in board.legal_moves:
        return best_move.uci() if best_move else None, None, "illegal"

    before_board = board.copy(stack=False)
    board.push(move)
    after = engine.analyse(board, limit)
    after_score = score_cp(after["score"].relative)
    if board.turn != mover and after_score is not None:
        after_score = -after_score

    diff = (
        before_score - after_score
        if before_score is not None and after_score is not None
        else None
    )
    return (
        best_move.uci() if best_move else None,
        diff,
        classify_move(diff, before_board, move, before_score, after_score),
    )


def analyze_position(engine, fen, depth):
    board = chess.Board(fen)
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    best_move = info.get("pv", [None])[0]
    pv = [move.uci() for move in info.get("pv", [])[:8]]
    return (
        best_move.uci() if best_move else None,
        score_cp(info["score"].relative),
        pv,
    )


def open_stockfish(threads=1, hash_mb=None):
    errors = []
    for engine_path in [STOCKFISH_PATH, *STOCKFISH_FALLBACK_PATHS]:
        engine = None
        try:
            engine = chess.engine.SimpleEngine.popen_uci(
                engine_path,
                **STOCKFISH_POPEN_ARGS,
            )
            engine.configure(
                {
                    "Threads": max(1, int(threads)),
                    "Hash": max(16, int(hash_mb or STOCKFISH_HASH_MB)),
                }
            )
            return engine
        except Exception as exc:
            errors.append(f"{engine_path}: {exc}")
            if engine:
                try:
                    engine.quit()
                except Exception:
                    pass
    raise RuntimeError("Stockfish 시작 실패: " + " | ".join(errors))


class AnalysisRunControl:
    def __init__(self, job_id):
        self.job_id = job_id
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        self.engines = set()

    def stopped(self):
        return self.stop_event.is_set()

    def cancelled(self):
        return self.cancel_event.is_set()

    def register_engine(self, engine):
        with self.lock:
            if self.stop_event.is_set():
                try:
                    engine.quit()
                except Exception:
                    engine.close()
                return False
            self.engines.add(engine)
            return True

    def unregister_engine(self, engine):
        with self.lock:
            self.engines.discard(engine)

    def stop(self):
        self.stop_event.set()
        with self.lock:
            engines = list(self.engines)
        for engine in engines:
            try:
                engine.protocol.loop.call_soon_threadsafe(
                    engine.protocol.send_line,
                    "stop",
                )
            except Exception:
                pass

    def close_engines(self):
        self.stop_event.set()
        with self.lock:
            engines = list(self.engines)
        for engine in engines:
            try:
                engine.close()
            except Exception:
                pass

    def request_cancel(self):
        self.cancel_event.set()
        self.stop()


def analysis_worker_count(requested, position_count):
    available = max(1, (os.cpu_count() or 1) - 2)
    return max(1, min(int(requested), available, position_count))


def hash_per_worker(worker_count):
    return max(16, min(128, STOCKFISH_HASH_MB // max(1, worker_count)))


def job_cancelled(job_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT status FROM analysis_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return not row or row["status"] == "cancelled"


def analyze_rows_parallel(rows, depth, requested_workers, job_id, control=None):
    if not rows:
        return
    control = control or AnalysisRunControl(job_id)
    prepared = {}
    dependencies = {}
    positions = []
    seen_positions = set()

    for row in rows:
        before_fen = row["fen_before"]
        board = chess.Board(before_fen)
        move = chess.Move.from_uci(row["move"])
        legal = move in board.legal_moves
        if legal:
            board.push(move)
            after_fen = row["fen_after"] or board.fen()
            required = {before_fen, after_fen}
        else:
            after_fen = None
            required = {before_fen}
        prepared[row["id"]] = {
            "before_fen": before_fen,
            "after_fen": after_fen,
            "legal": legal,
            "move": row["move"],
        }
        dependencies[row["id"]] = required
        for fen in required:
            if fen not in seen_positions:
                seen_positions.add(fen)
                positions.append(fen)

    worker_count = analysis_worker_count(requested_workers, len(positions))
    work_queue = queue.Queue()
    result_queue = queue.Queue()
    for fen in positions:
        work_queue.put(fen)

    def run_engine_worker():
        engine = None
        try:
            engine = open_stockfish(
                threads=1,
                hash_mb=hash_per_worker(worker_count),
            )
            if not control.register_engine(engine):
                return
            while not control.stopped():
                try:
                    fen = work_queue.get_nowait()
                except queue.Empty:
                    break
                result_queue.put(
                    ("result", fen, analyze_position(engine, fen, depth))
                )
        except Exception as exc:
            if not control.cancelled():
                control.stop()
                result_queue.put(("error", None, exc))
        finally:
            if engine:
                control.unregister_engine(engine)
                try:
                    engine.quit()
                except Exception:
                    try:
                        engine.close()
                    except Exception:
                        pass
            result_queue.put(("done", None, None))

    workers = [
        threading.Thread(
            target=run_engine_worker,
            name=f"stockfish-worker-{index}",
        )
        for index in range(worker_count)
    ]
    for worker_thread in workers:
        worker_thread.start()

    dependents = {}
    for move_id, required in dependencies.items():
        for fen in required:
            dependents.setdefault(fen, []).append(move_id)

    cache = {}
    completed_moves = set()
    completed_workers = 0
    worker_error = None
    next_cancel_check = time.monotonic() + 0.25

    try:
        while completed_workers < worker_count:
            try:
                kind, fen, payload = result_queue.get(timeout=0.25)
            except queue.Empty:
                if job_cancelled(job_id):
                    control.request_cancel()
                continue

            if kind == "done":
                completed_workers += 1
                continue
            if kind == "error":
                worker_error = payload
                control.stop()
                continue

            cache[fen] = payload
            for move_id in dependents.get(fen, []):
                if move_id in completed_moves:
                    continue
                if not dependencies[move_id].issubset(cache):
                    continue
                completed_moves.add(move_id)
                move = prepared[move_id]
                best_move, before_score, best_line = cache[move["before_fen"]]
                if not move["legal"]:
                    yield move_id, best_move, best_line, [], None, "illegal"
                    continue
                _, after_score, reply_line = cache[move["after_fen"]]
                diff = (
                    before_score + after_score
                    if before_score is not None and after_score is not None
                    else None
                )
                before_board = chess.Board(move["before_fen"])
                played_move = chess.Move.from_uci(move["move"])
                mover_after_score = -after_score if after_score is not None else None
                yield (
                    move_id,
                    best_move,
                    best_line,
                    reply_line,
                    diff,
                    classify_move(
                        diff,
                        before_board,
                        played_move,
                        before_score,
                        mover_after_score,
                    ),
                )

            if time.monotonic() >= next_cancel_check:
                if job_cancelled(job_id):
                    control.request_cancel()
                next_cancel_check = time.monotonic() + 0.25
    finally:
        if control.cancelled():
            control.stop()
        for worker_thread in workers:
            worker_thread.join()

    if worker_error and not control.cancelled():
        raise worker_error


def normalize_accounts(accounts):
    normalized = []
    for account in accounts or []:
        provider = (account.get("provider") or "").strip().lower()
        username = (account.get("username") or "").strip()
        if provider in {"chesscom", "lichess"} and username:
            normalized.append({"provider": provider, "username": username})
    return sorted(normalized, key=lambda item: (item["provider"], item["username"].casefold()))


def account_where(accounts):
    clauses = []
    params = []
    for account in accounts:
        clauses.append("(g.provider = ? AND lower(g.player_username) = lower(?))")
        params.extend([account["provider"], account["username"]])
    return " OR ".join(clauses), params


def estimate_seconds(move_count, depth, threads):
    depth = min(DEPTH_SECONDS, key=lambda value: abs(value - int(depth)))
    threads = max(1, int(threads))
    worker_gain = min(threads, 6)
    return max(1, round(move_count * DEPTH_SECONDS[depth] / worker_gain))


def accounts_key(accounts):
    return json.dumps(
        normalize_accounts(accounts),
        ensure_ascii=True,
        sort_keys=True,
    )


def active_job_id(accounts):
    key = accounts_key(accounts)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM analysis_jobs
            WHERE accounts_json = ? AND status IN ('queued', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (key,),
        ).fetchone()
    return row["id"] if row else None


def queue_missing_opponent_moves():
    queued = 0
    with connect() as conn:
        jobs = conn.execute(
            """
            SELECT id, accounts_json, depth
            FROM analysis_jobs
            WHERE status = 'completed'
              AND accounts_json IS NOT NULL
              AND id IN (
                  SELECT MAX(id)
                  FROM analysis_jobs
                  WHERE status = 'completed' AND accounts_json IS NOT NULL
                  GROUP BY accounts_json
              )
            """
        ).fetchall()
        for job in jobs:
            try:
                accounts = normalize_accounts(json.loads(job["accounts_json"]))
            except (TypeError, ValueError):
                continue
            if not accounts:
                continue
            where_sql, params = account_where(accounts)
            depth = job["depth"] or DEFAULT_ANALYSIS_DEPTH
            rows = conn.execute(
                f"""
                SELECT m.id
                FROM moves m
                JOIN games g ON g.id = m.game_id
                WHERE m.is_player_move = 0
                  AND ({where_sql})
                  AND COALESCE(m.analysis_depth, 0) < ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM analysis_job_moves jm
                      WHERE jm.job_id = ? AND jm.move_id = m.id
                  )
                """,
                [*params, depth, job["id"]],
            ).fetchall()
            if not rows:
                continue
            conn.executemany(
                """
                INSERT INTO analysis_job_moves(job_id, move_id, status)
                VALUES (?, ?, 'pending')
                """,
                [(job["id"], row["id"]) for row in rows],
            )
            _sync_job_counts(conn, job["id"])
            conn.execute(
                """
                UPDATE analysis_jobs
                SET status = 'queued', completed_at = NULL,
                    error_message = NULL,
                    run_started_completed = completed_moves
                WHERE id = ?
                """,
                (job["id"],),
            )
            queued += len(rows)
    return queued


def _commit_analysis_updates(job_id, updates, control):
    if not updates or control.cancelled():
        return False
    with connect() as conn:
        status = conn.execute(
            "SELECT status FROM analysis_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not status or status["status"] != "running":
            control.request_cancel()
            return False
        conn.executemany(
            """
            UPDATE moves
            SET best_move = ?, best_line = ?, reply_line = ?,
                eval_diff = ?, mistake_type = ?,
                analyzed_at = ?, analysis_depth = ?
            WHERE id = ?
              AND COALESCE(analysis_depth, 0) <= ?
            """,
            updates,
        )
        _propagate_matching_higher_depth(conn, [update[-2] for update in updates])
        conn.executemany(
            """
            UPDATE analysis_job_moves
            SET status = 'completed'
            WHERE job_id = ? AND move_id = ?
            """,
            [(job_id, update[-2]) for update in updates],
        )
        _sync_job_counts(conn, job_id)
    return True


def _propagate_matching_higher_depth(conn, move_ids):
    if not move_ids:
        return
    placeholders = ",".join("?" for _ in move_ids)
    sources = conn.execute(
        f"""
        SELECT id, fen_before, move, best_move, best_line, reply_line,
               eval_diff, mistake_type, analyzed_at, analysis_depth
        FROM moves
        WHERE id IN ({placeholders})
          AND COALESCE(analysis_depth, 0) > 0
        """,
        move_ids,
    ).fetchall()
    for source in sources:
        conn.execute(
            """
            UPDATE moves
            SET best_move = ?, best_line = ?, reply_line = ?,
                eval_diff = ?, mistake_type = ?,
                analyzed_at = ?, analysis_depth = ?
            WHERE fen_before = ?
              AND move = ?
              AND COALESCE(analysis_depth, 0) < ?
            """,
            (
                source["best_move"],
                source["best_line"],
                source["reply_line"],
                source["eval_diff"],
                source["mistake_type"],
                source["analyzed_at"],
                source["analysis_depth"],
                source["fen_before"],
                source["move"],
                source["analysis_depth"],
            ),
        )


class AnalysisWorker:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self.lock = threading.Lock()
        self.active_job_id = None
        self.active_control = None
        self.active_future = None
        self.stopping = False

    def resume(self):
        with connect() as conn:
            resumable_jobs = conn.execute(
                """
                SELECT id, depth
                FROM analysis_jobs
                WHERE status = 'running'
                   OR (
                       status = 'failed'
                       AND error_message LIKE 'engine process died unexpectedly%'
                   )
                """
            ).fetchall()
            for job in resumable_jobs:
                _reuse_analyzed_moves(
                    conn,
                    job["id"],
                    job["depth"] or DEFAULT_ANALYSIS_DEPTH,
                )
                pending = conn.execute(
                    """
                    SELECT 1 FROM analysis_job_moves
                    WHERE job_id = ? AND status = 'pending' LIMIT 1
                    """,
                    (job["id"],),
                ).fetchone()
                if pending:
                    _requeue_job(conn, job["id"])
                else:
                    _complete_job(conn, job["id"])
            duplicate_groups = conn.execute(
                """
                SELECT accounts_json, depth, threads
                FROM analysis_jobs
                WHERE status = 'queued'
                GROUP BY accounts_json, depth, threads
                HAVING COUNT(*) > 1
                """
            ).fetchall()
            for group in duplicate_groups:
                jobs = conn.execute(
                    """
                    SELECT id, completed_moves
                    FROM analysis_jobs
                    WHERE status = 'queued'
                      AND accounts_json = ?
                      AND depth = ?
                      AND threads = ?
                    ORDER BY completed_moves DESC, id DESC
                    """,
                    (group["accounts_json"], group["depth"], group["threads"]),
                ).fetchall()
                keep_id = jobs[0]["id"]
                conn.executemany(
                    """
                    UPDATE analysis_jobs
                    SET status = 'cancelled', completed_at = ?,
                        error_message = 'duplicate analysis job'
                    WHERE id = ?
                    """,
                    [(utc_now(), job["id"]) for job in jobs if job["id"] != keep_id],
                )
            row = conn.execute(
                """
                SELECT id FROM analysis_jobs
                WHERE status = 'queued'
                ORDER BY completed_moves DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row:
            self.start(row["id"])

    def start(self, job_id):
        with self.lock:
            if self.stopping or self.active_job_id is not None:
                return False
            control = AnalysisRunControl(job_id)
            self.active_job_id = job_id
            self.active_control = control
            self.active_future = self.executor.submit(self._run, job_id, control)
            return True

    def request_cancel(self, job_id):
        with self.lock:
            control = (
                self.active_control
                if self.active_job_id == job_id
                else None
            )
        if control:
            control.request_cancel()
            return True
        return False

    def shutdown(self, timeout=5):
        with self.lock:
            self.stopping = True
            control = self.active_control
            future = self.active_future
        completed = future is None
        if control:
            control.request_cancel()
        if future:
            try:
                future.result(timeout=timeout)
                completed = True
            except FutureTimeoutError:
                if control:
                    control.close_engines()
            except Exception:
                completed = True
        self.executor.shutdown(wait=completed, cancel_futures=True)

    def _start_next(self, control):
        with self.lock:
            if self.active_control is not control:
                return
            self.active_job_id = None
            self.active_control = None
            self.active_future = None
            stopping = self.stopping
        if stopping:
            return
        with connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM analysis_jobs
                WHERE status = 'queued'
                ORDER BY completed_moves DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row:
            self.start(row["id"])

    def _run(self, job_id, control):
        try:
            with connect() as conn:
                job = conn.execute(
                    "SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if (
                    not job
                    or job["status"] not in {"queued", "running"}
                    or control.cancelled()
                ):
                    return
                depth = job["depth"] or DEFAULT_ANALYSIS_DEPTH
                threads = job["threads"] or DEFAULT_ANALYSIS_WORKERS
                cursor = conn.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'running', started_at = ?, error_message = NULL
                    WHERE id = ? AND status IN ('queued', 'running')
                    """,
                    (utc_now(), job_id),
                )
                if cursor.rowcount == 0:
                    return

            while not control.cancelled():
                with connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT m.id, m.fen_before, m.fen_after, m.move
                        FROM analysis_job_moves jm
                        JOIN moves m ON m.id = jm.move_id
                        WHERE jm.job_id = ? AND jm.status = 'pending'
                        ORDER BY m.game_id, m.ply
                        LIMIT ?
                        """,
                        (job_id, ANALYSIS_CHUNK_SIZE),
                    ).fetchall()
                if not rows:
                    break

                pending_updates = []
                for analysis_result in analyze_rows_parallel(
                    rows,
                    depth,
                    threads,
                    job_id,
                    control,
                ):
                    if len(analysis_result) == 4:
                        move_id, best_move, diff, mistake = analysis_result
                        best_line = []
                        reply_line = []
                    else:
                        (
                            move_id,
                            best_move,
                            best_line,
                            reply_line,
                            diff,
                            mistake,
                        ) = analysis_result
                    if control.cancelled():
                        break
                    pending_updates.append(
                        (
                            best_move,
                            json.dumps(best_line or [], ensure_ascii=True),
                            json.dumps(reply_line or [], ensure_ascii=True),
                            diff,
                            mistake,
                            utc_now(),
                            depth,
                            move_id,
                            depth,
                        )
                    )
                    if len(pending_updates) < DATABASE_WRITE_BATCH_SIZE:
                        continue
                    if not _commit_analysis_updates(
                        job_id,
                        pending_updates,
                        control,
                    ):
                        break
                    pending_updates = []

                if pending_updates and not _commit_analysis_updates(
                    job_id,
                    pending_updates,
                    control,
                ):
                    break

            if not control.cancelled():
                with connect() as conn:
                    _sync_job_counts(conn, job_id)
                    pending = conn.execute(
                        """
                        SELECT 1 FROM analysis_job_moves
                        WHERE job_id = ? AND status = 'pending'
                        LIMIT 1
                        """,
                        (job_id,),
                    ).fetchone()
                    if pending:
                        conn.execute(
                            """
                            UPDATE analysis_jobs
                            SET status = 'failed',
                                error_message = 'analysis ended with pending moves',
                                completed_at = ?
                            WHERE id = ? AND status = 'running'
                            """,
                            (utc_now(), job_id),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE analysis_jobs
                            SET status = 'completed', completed_at = ?
                            WHERE id = ? AND status = 'running'
                            """,
                            (utc_now(), job_id),
                        )
        except Exception as exc:
            if not control.cancelled():
                with connect() as conn:
                    conn.execute(
                        """
                        UPDATE analysis_jobs
                        SET status = 'failed', error_message = ?, completed_at = ?
                        WHERE id = ? AND status = 'running'
                        """,
                        (str(exc), utc_now(), job_id),
                    )
        finally:
            control.stop()
            self._start_next(control)


worker = AnalysisWorker()


def create_job(accounts, depth, threads, move_ids=None):
    accounts = normalize_accounts(accounts)
    if not accounts:
        raise ValueError("분석할 계정이 없습니다.")
    depth = max(8, min(16, int(depth)))
    threads = max(1, min(16, int(threads)))
    accounts_json = accounts_key(accounts)
    where_sql, params = account_where(accounts)
    should_start = True

    with connect() as conn:
        active = conn.execute(
            """
            SELECT id, depth FROM analysis_jobs
            WHERE accounts_json = ? AND status IN ('queued', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (accounts_json,),
        ).fetchone()
        if active and not (move_ids and (active["depth"] or 0) < depth):
            if move_ids:
                unique_ids = _filter_unanalyzed_move_ids(conn, move_ids, depth)
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO analysis_job_moves(job_id, move_id, status)
                    VALUES (?, ?, 'pending')
                    """,
                    [(active["id"], move_id) for move_id in unique_ids],
                )
                conn.execute(
                    """
                    UPDATE analysis_jobs
                    SET total_moves = (
                        SELECT COUNT(*) FROM analysis_job_moves WHERE job_id = ?
                    )
                    WHERE id = ?
                    """,
                    (active["id"], active["id"]),
                )
            return active["id"], False

        resumable = conn.execute(
            """
            SELECT id FROM analysis_jobs
            WHERE accounts_json = ?
              AND depth = ?
              AND threads = ?
              AND status IN ('failed', 'cancelled')
              AND EXISTS (
                  SELECT 1 FROM analysis_job_moves
                  WHERE job_id = analysis_jobs.id AND status = 'pending'
              )
            ORDER BY id DESC LIMIT 1
            """,
            (accounts_json, depth, threads),
        ).fetchone()
        if resumable and move_ids is None:
            _reuse_analyzed_moves(conn, resumable["id"], depth)
            pending = conn.execute(
                """
                SELECT 1 FROM analysis_job_moves
                WHERE job_id = ? AND status = 'pending' LIMIT 1
                """,
                (resumable["id"],),
            ).fetchone()
            if not pending:
                _complete_job(conn, resumable["id"])
                return resumable["id"], False
            _requeue_job(conn, resumable["id"])
            job_id = resumable["id"]
            should_resume = True
        else:
            should_resume = False

        if not should_resume:
            cursor = conn.execute(
                """
                INSERT INTO analysis_jobs (
                    player_username, status, time_limit_ms, total_moves,
                    completed_moves, created_at, accounts_json, depth, threads
                ) VALUES (?, 'queued', 0, 0, 0, ?, ?, ?, ?)
                """,
                (
                    ", ".join(account["username"] for account in accounts),
                    utc_now(),
                    accounts_json,
                    depth,
                    threads,
                ),
            )
            job_id = cursor.lastrowid
            if move_ids is None:
                rows = conn.execute(
                    f"""
                    SELECT m.id
                    FROM moves m
                    JOIN games g ON g.id = m.game_id
                    WHERE ({where_sql})
                      AND COALESCE(m.analysis_depth, 0) < ?
                    ORDER BY g.date DESC, g.id DESC, m.ply DESC
                    """,
                    [*params, depth],
                ).fetchall()
            else:
                unique_ids = _filter_unanalyzed_move_ids(conn, move_ids, depth)
                rows = [{"id": move_id} for move_id in unique_ids]
            conn.executemany(
                """
                INSERT INTO analysis_job_moves(job_id, move_id, status)
                VALUES (?, ?, 'pending')
                """,
                [(job_id, row["id"]) for row in rows],
            )
            _sync_job_counts(conn, job_id)
            if not rows:
                _complete_job(conn, job_id)
                should_start = False

    if should_start:
        worker.start(job_id)
    return job_id, True


def _filter_unanalyzed_move_ids(conn, move_ids, depth):
    unique_ids = list(dict.fromkeys(int(move_id) for move_id in move_ids))
    if not unique_ids:
        return []
    placeholders = ",".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"""
        SELECT id
        FROM moves
        WHERE id IN ({placeholders})
          AND COALESCE(analysis_depth, 0) < ?
        """,
        [*unique_ids, depth],
    ).fetchall()
    unanalyzed = {row["id"] for row in rows}
    return [move_id for move_id in unique_ids if move_id in unanalyzed]


def cancel_job(job_id):
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE analysis_jobs
            SET status = 'cancelled', completed_at = ?
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (utc_now(), job_id),
        )
    cancelled = cursor.rowcount > 0
    if cancelled:
        worker.request_cancel(job_id)
    return cancelled


def _sync_job_counts(conn, job_id):
    counts = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed
        FROM analysis_job_moves
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE analysis_jobs
        SET total_moves = ?, completed_moves = ?
        WHERE id = ?
        """,
        (counts["total"] or 0, counts["completed"] or 0, job_id),
    )


def _requeue_job(conn, job_id):
    _sync_job_counts(conn, job_id)
    completed = conn.execute(
        "SELECT completed_moves FROM analysis_jobs WHERE id = ?", (job_id,)
    ).fetchone()["completed_moves"]
    conn.execute(
        """
        UPDATE analysis_jobs
        SET status = 'queued', error_message = NULL,
            completed_at = NULL, started_at = NULL,
            run_started_completed = ?
        WHERE id = ?
        """,
        (completed, job_id),
    )


def _reuse_analyzed_moves(conn, job_id, depth):
    conn.execute(
        """
        UPDATE analysis_job_moves
        SET status = 'completed'
        WHERE job_id = ? AND status = 'pending'
          AND move_id IN (
              SELECT id FROM moves
              WHERE COALESCE(analysis_depth, 0) >= ?
          )
        """,
        (job_id, depth),
    )
    _sync_job_counts(conn, job_id)


def _complete_job(conn, job_id):
    _sync_job_counts(conn, job_id)
    conn.execute(
        """
        UPDATE analysis_jobs
        SET status = 'completed', completed_at = ?, error_message = NULL
        WHERE id = ?
        """,
        (utc_now(), job_id),
    )


def resume_job(job_id):
    with connect() as conn:
        job = conn.execute(
            "SELECT status, depth FROM analysis_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not job or job["status"] not in {"failed", "cancelled"}:
            return False
        _reuse_analyzed_moves(
            conn,
            job_id,
            job["depth"] or DEFAULT_ANALYSIS_DEPTH,
        )
        pending = conn.execute(
            """
            SELECT 1 FROM analysis_job_moves
            WHERE job_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        if not pending:
            _complete_job(conn, job_id)
            return True
        _requeue_job(conn, job_id)
    worker.start(job_id)
    return True


def latest_completed_settings(accounts):
    accounts = normalize_accounts(accounts)
    if not accounts:
        return None
    accounts_json = accounts_key(accounts)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT depth, threads
            FROM analysis_jobs
            WHERE accounts_json = ? AND status = 'completed'
            ORDER BY id DESC LIMIT 1
            """,
            (accounts_json,),
        ).fetchone()
    if not row:
        return None
    return {
        "depth": row["depth"] or DEFAULT_ANALYSIS_DEPTH,
        "threads": row["threads"] or DEFAULT_ANALYSIS_WORKERS,
    }


def job_payload(job_id):
    with connect() as conn:
        _sync_job_counts(conn, job_id)
        row = conn.execute(
            "SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if not row:
        return None

    total = row["total_moves"]
    completed = row["completed_moves"]
    depth = row["depth"] or DEFAULT_ANALYSIS_DEPTH
    threads = row["threads"] or DEFAULT_ANALYSIS_WORKERS
    remaining = estimate_seconds(max(total - completed, 0), depth, threads)
    if row["started_at"] and completed:
        elapsed = max(0, int(time.time() - _iso_timestamp(row["started_at"])))
        session_completed = completed - (row["run_started_completed"] or 0)
        if session_completed > 0:
            remaining = round((elapsed / session_completed) * (total - completed))

    return {
        "id": row["id"],
        "accounts": json.loads(row["accounts_json"] or "[]"),
        "status": row["status"],
        "status_label": STATUS_LABELS.get(row["status"], row["status"]),
        "depth": depth,
        "threads": threads,
        "total_moves": total,
        "completed_moves": completed,
        "progress": round(completed / total * 100, 1) if total else 0,
        "estimated_remaining_seconds": remaining,
        "error_message": row["error_message"],
    }


def _iso_timestamp(value):
    from datetime import datetime

    return datetime.fromisoformat(value).timestamp()
