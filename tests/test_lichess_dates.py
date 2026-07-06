import gc
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


class LichessDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db = PROJECT_DIR / "output" / f"lichess-dates-{uuid.uuid4().hex}.db"
        cls.original_db_path = os.environ.get("CHECKSS_DB_PATH")
        os.environ["CHECKSS_DB_PATH"] = str(cls.test_db)
        cls.database = importlib.import_module("database")
        cls.original_module_db_path = cls.database.DB_PATH
        cls.database.DB_PATH = cls.test_db
        cls.database.init_db()
        cls.lichess = importlib.import_module("lichess")

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
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{cls.test_db}{suffix}")
            for _attempt in range(20):
                if not path.exists():
                    break
                try:
                    path.unlink()
                    break
                except PermissionError:
                    gc.collect()
                    time.sleep(0.05)

    def test_latest_game_date_ignores_partial_pgn_dates(self):
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO games (white, black, date, player_username, provider)
                VALUES ('tester', 'opponent', '????.??.??', 'tester', 'lichess')
                """
            )
            conn.execute(
                """
                INSERT INTO games (white, black, date, player_username, provider)
                VALUES ('tester', 'opponent', '2026.06.30', 'tester', 'lichess')
                """
            )

        self.assertEqual(
            self.database.latest_game_date("tester", "lichess"),
            "2026-06-30",
        )

    def test_lichess_import_skips_invalid_since_date(self):
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append({"url": url, "params": params or {}})
            response = mock.Mock()
            response.raise_for_status.return_value = None
            if url.endswith("/api/user/tester"):
                response.json.return_value = {"username": "tester"}
            else:
                response.text = ""
            return response

        with mock.patch.object(self.lichess.requests, "get", side_effect=fake_get):
            username, pgn = self.lichess.fetch_player_pgn(
                "tester",
                since_date="????-??-??",
            )

        self.assertEqual(username, "tester")
        self.assertEqual(pgn, "")
        games_call = calls[-1]
        self.assertNotIn("since", games_call["params"])

    def test_import_pgn_skips_existing_games_without_shape_error(self):
        pgn = """
[Event "Rated rapid game"]
[Site "https://lichess.org/reimportTest"]
[Date "2026.06.30"]
[Round "-"]
[White "tester"]
[Black "opponent"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""

        first = self.database.import_pgn(pgn, "tester", provider="lichess")
        second = self.database.import_pgn(pgn, "tester", provider="lichess")

        self.assertEqual(first["added_games"], 1)
        self.assertEqual(second["added_games"], 0)
        self.assertEqual(second["skipped_games"], 1)


if __name__ == "__main__":
    unittest.main()
