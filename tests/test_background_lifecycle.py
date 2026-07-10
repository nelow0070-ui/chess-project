import gc
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import analysis_service
import database
import launcher


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return None


class LauncherTests(unittest.TestCase):
    def test_existing_checkss_is_found_before_free_lower_port(self):
        with (
            mock.patch.object(launcher, "PORT_RANGE", range(5000, 5003)),
            mock.patch.object(
                launcher,
                "checkss_is_running",
                side_effect=lambda port: port == 5001,
            ),
            mock.patch.object(
                launcher,
                "port_is_available",
                side_effect=lambda port: port == 5000,
            ),
        ):
            self.assertEqual(launcher.select_port(), (5001, True))

    @unittest.skipUnless(sys.platform == "win32", "Windows mutex test")
    def test_named_mutex_detects_duplicate_instance(self):
        first = second = None
        mutex_name = f"Local\\checkss-test-{uuid.uuid4().hex}"
        try:
            first, first_duplicate = launcher.acquire_instance_mutex(mutex_name)
            second, second_duplicate = launcher.acquire_instance_mutex(mutex_name)
            self.assertFalse(first_duplicate)
            self.assertTrue(second_duplicate)
        finally:
            launcher.release_instance_mutex(second)
            launcher.release_instance_mutex(first)


class AnalysisLifecycleTests(unittest.TestCase):
    def setUp(self):
        test_root = PROJECT_DIR / "output"
        test_root.mkdir(exist_ok=True)
        self.original_db_path = database.DB_PATH
        self.original_worker = analysis_service.worker
        database.DB_PATH = test_root / f"lifecycle-{uuid.uuid4().hex}.db"
        database.init_db()
        self.worker = analysis_service.AnalysisWorker()
        analysis_service.worker = self.worker

    def tearDown(self):
        self.worker.shutdown(timeout=2)
        analysis_service.worker = self.original_worker
        test_db_path = database.DB_PATH
        database.DB_PATH = self.original_db_path
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{test_db_path}{suffix}")
            for _attempt in range(20):
                if not path.exists():
                    break
                try:
                    path.unlink()
                    break
                except PermissionError:
                    gc.collect()
                    time.sleep(0.05)

    def add_moves(self, count):
        with database.connect() as conn:
            game_id = conn.execute(
                """
                INSERT INTO games (
                    white, black, result, player_username, player_color, provider
                ) VALUES ('tester', 'opponent', '1-0', 'tester', 'white', 'chesscom')
                """
            ).lastrowid
            move_ids = []
            for ply in range(1, count + 1):
                move_ids.append(
                    conn.execute(
                        """
                        INSERT INTO moves (
                            game_id, ply, fen_before, fen_after, move, is_player_move
                        ) VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (game_id, ply, f"before-{ply}", f"after-{ply}", "e2e4"),
                    ).lastrowid
                )
        return move_ids

    def job_status(self, job_id):
        with database.connect() as conn:
            return conn.execute(
                """
                SELECT status, total_moves, completed_moves
                FROM analysis_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()

    def test_cancel_then_immediate_resume_finishes_pending_moves(self):
        move_ids = self.add_moves(3)
        first_run_started = threading.Event()
        call_count = 0

        def fake_analyze(rows, _depth, _threads, _job_id, control=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_run_started.set()
                while not control.cancelled():
                    time.sleep(0.01)
                return
            for row in rows:
                yield row["id"], "e2e4", 0, "best"

        with mock.patch.object(
            analysis_service,
            "analyze_rows_parallel",
            side_effect=fake_analyze,
        ):
            job_id, created = analysis_service.create_job(
                [{"provider": "chesscom", "username": "tester"}],
                depth=14,
                threads=2,
                move_ids=move_ids,
            )
            self.assertTrue(created)
            self.assertTrue(first_run_started.wait(2))
            self.assertTrue(
                wait_until(lambda: self.job_status(job_id)["status"] == "running")
            )

            self.assertTrue(analysis_service.cancel_job(job_id))
            self.assertTrue(analysis_service.resume_job(job_id))

            completed = wait_until(
                lambda: (
                    row
                    if (row := self.job_status(job_id))["status"] == "completed"
                    else None
                ),
                timeout=5,
            )
            self.assertIsNotNone(completed)
            self.assertEqual(completed["completed_moves"], 3)
            self.assertEqual(completed["total_moves"], 3)
            self.assertGreaterEqual(call_count, 2)

            with database.connect() as conn:
                pending = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM analysis_job_moves
                    WHERE job_id = ? AND status = 'pending'
                    """,
                    (job_id,),
                ).fetchone()["count"]
            self.assertEqual(pending, 0)

    def test_explicit_move_ids_skip_already_analyzed_moves(self):
        move_ids = self.add_moves(3)
        with database.connect() as conn:
            conn.execute(
                "UPDATE moves SET analysis_depth = 14 WHERE id = ?",
                (move_ids[0],),
            )

        with mock.patch.object(self.worker, "start") as start:
            job_id, created = analysis_service.create_job(
                [{"provider": "chesscom", "username": "tester"}],
                depth=14,
                threads=2,
                move_ids=move_ids,
            )

        self.assertTrue(created)
        start.assert_called_once_with(job_id)
        with database.connect() as conn:
            queued_ids = [
                row["move_id"]
                for row in conn.execute(
                    """
                    SELECT move_id
                    FROM analysis_job_moves
                    WHERE job_id = ?
                    ORDER BY move_id
                    """,
                    (job_id,),
                )
            ]
        self.assertEqual(queued_ids, move_ids[1:])

    def test_hash_budget_is_shared_across_workers(self):
        for worker_count in (1, 2, 4, 6, 8, 16):
            allocated = (
                analysis_service.hash_per_worker(worker_count) * worker_count
            )
            allowance = max(
                analysis_service.STOCKFISH_HASH_MB,
                16 * worker_count,
            )
            self.assertLessEqual(allocated, allowance)


if __name__ == "__main__":
    unittest.main()
