import importlib
import os
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class StartupRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db = (
            PROJECT_DIR / "output" / f"startup-routing-{uuid.uuid4().hex}.db"
        )
        cls.original_db_path = os.environ.get("CHECKSS_DB_PATH")
        cls.original_disable_worker = os.environ.get("CHECKSS_DISABLE_WORKER")
        os.environ["CHECKSS_DB_PATH"] = str(cls.test_db)
        os.environ["CHECKSS_DISABLE_WORKER"] = "1"
        cls.database = importlib.import_module("database")
        cls.original_module_db_path = cls.database.DB_PATH
        cls.database.DB_PATH = cls.test_db
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    def setUp(self):
        with self.database.connect() as conn:
            conn.execute("DELETE FROM analysis_job_moves")
            conn.execute("DELETE FROM analysis_jobs")
            conn.execute("DELETE FROM moves")
            conn.execute("DELETE FROM games")

    @classmethod
    def tearDownClass(cls):
        cls.database.DB_PATH = cls.original_module_db_path
        if cls.original_db_path is None:
            os.environ.pop("CHECKSS_DB_PATH", None)
        else:
            os.environ["CHECKSS_DB_PATH"] = cls.original_db_path
        if cls.original_disable_worker is None:
            os.environ.pop("CHECKSS_DISABLE_WORKER", None)
        else:
            os.environ["CHECKSS_DISABLE_WORKER"] = cls.original_disable_worker
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{cls.test_db}{suffix}")
            for _attempt in range(20):
                if not path.exists():
                    break
                try:
                    path.unlink()
                    break
                except PermissionError:
                    time.sleep(0.05)

    def test_active_analysis_takes_priority_over_partial_results(self):
        with (
            mock.patch.object(
                self.server,
                "active_analysis_jobs",
                return_value=1,
            ),
            mock.patch.object(
                self.server,
                "has_analysis_results",
                return_value=True,
            ),
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/analyzing")

    def test_restarted_partial_job_opens_analyzing_page(self):
        with self.database.connect() as conn:
            game_id = conn.execute(
                """
                INSERT INTO games (
                    white, black, result, player_username, player_color, provider
                ) VALUES ('tester', 'opponent', '1-0', 'tester', 'white', 'chesscom')
                """
            ).lastrowid
            completed_move_id = conn.execute(
                """
                INSERT INTO moves (
                    game_id, ply, fen_before, fen_after, move,
                    is_player_move, best_move, analyzed_at, analysis_depth
                ) VALUES (?, 1, 'before-1', 'after-1', 'e2e4',
                          1, 'e2e4', ?, 14)
                """,
                (game_id, self.database.utc_now()),
            ).lastrowid
            pending_move_id = conn.execute(
                """
                INSERT INTO moves (
                    game_id, ply, fen_before, fen_after, move, is_player_move
                ) VALUES (?, 2, 'before-2', 'after-2', 'e7e5', 0)
                """,
                (game_id,),
            ).lastrowid
            job_id = conn.execute(
                """
                INSERT INTO analysis_jobs (
                    player_username, status, time_limit_ms,
                    total_moves, completed_moves, created_at,
                    accounts_json, depth, threads
                ) VALUES ('tester', 'running', 0, 2, 1, ?, '[]', 14, 2)
                """,
                (self.database.utc_now(),),
            ).lastrowid
            conn.executemany(
                """
                INSERT INTO analysis_job_moves(job_id, move_id, status)
                VALUES (?, ?, ?)
                """,
                [
                    (job_id, completed_move_id, "completed"),
                    (job_id, pending_move_id, "pending"),
                ],
            )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/analyzing")

    def test_completed_results_without_active_job_open_board(self):
        with (
            mock.patch.object(
                self.server,
                "active_analysis_jobs",
                return_value=0,
            ),
            mock.patch.object(
                self.server,
                "has_analysis_results",
                return_value=True,
            ),
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/board")

    def test_add_games_flow_opens_accounts_even_with_completed_results(self):
        with (
            mock.patch.object(
                self.server,
                "active_analysis_jobs",
                return_value=0,
            ),
            mock.patch.object(
                self.server,
                "has_analysis_results",
                return_value=True,
            ),
        ):
            response = self.client.get("/?flow=add-games")

        self.assertEqual(response.status_code, 200)
        self.assertIn("계정 추가", response.get_data(as_text=True))

    def test_empty_database_opens_accounts_page(self):
        with (
            mock.patch.object(
                self.server,
                "active_analysis_jobs",
                return_value=0,
            ),
            mock.patch.object(
                self.server,
                "has_analysis_results",
                return_value=False,
            ),
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("계정 연결", response.get_data(as_text=True))

    def test_import_unexpected_error_returns_json(self):
        def fail_import(_username):
            raise ValueError("invalid date format")

        with mock.patch.dict(
            self.server.IMPORTERS,
            {"lichess": (fail_import, self.server.LichessError)},
        ):
            response = self.client.post(
                "/api/import",
                json={"provider": "lichess", "username": "tester"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content_type, "application/json")
        self.assertNotIn("invalid date format", response.get_json()["error"])
        self.assertIn("게임을 불러오지 못했습니다", response.get_json()["error"])

    def test_eval_rejects_overlong_fen_before_engine_start(self):
        response = self.client.get("/eval", query_string={"fen": "x" * 121})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "fen is too long")

    def test_eval_rate_limits_repeated_requests(self):
        self.server.eval_request_times.clear()
        with mock.patch.object(self.server, "EVAL_RATE_LIMIT_REQUESTS", 1):
            first = self.client.get("/eval", query_string={"fen": "invalid"})
            second = self.client.get("/eval", query_string={"fen": "invalid"})

        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json()["error"], "too many eval requests")

    def test_moves_winrate_uses_player_color_for_opponent_moves(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        with self.database.connect() as conn:
            game_id = conn.execute(
                """
                INSERT INTO games (
                    white, black, result, player_username, player_color, provider
                ) VALUES ('tester', 'opponent', '1-0', 'tester', 'white', 'chesscom')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO moves (
                    game_id, ply, turn, fen_before, fen_key, move, san,
                    is_player_move
                ) VALUES (?, 1, 'black', ?, ?, 'e7e5', 'e5', 0)
                """,
                (game_id, fen, self.database.normalize_fen(fen)),
            )

        response = self.client.get(
            "/moves",
            query_string={
                "fen": fen,
                "perspective": "opponent",
                "chesscom": "tester",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["wins"], 1)
        self.assertEqual(data[0]["losses"], 0)
        self.assertEqual(data[0]["winrate"], 100.0)


if __name__ == "__main__":
    unittest.main()
