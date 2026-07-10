import hashlib
import io
import sqlite3
from datetime import datetime, timezone

import chess.pgn

from config import DB_PATH


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                white TEXT,
                black TEXT,
                result TEXT,
                date TEXT,
                event TEXT,
                site TEXT,
                round TEXT,
                link TEXT,
                player_username TEXT,
                player_color TEXT,
                time_control TEXT,
                time_class TEXT
            );

            CREATE TABLE IF NOT EXISTS moves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                ply INTEGER,
                move_number INTEGER,
                turn TEXT,
                fen_before TEXT,
                fen_key TEXT,
                move TEXT,
                san TEXT,
                fen_after TEXT,
                best_move TEXT,
                best_line TEXT,
                reply_line TEXT,
                eval_diff INTEGER,
                mistake_type TEXT,
                is_player_move INTEGER,
                FOREIGN KEY(game_id) REFERENCES games(id)
            );

            CREATE TABLE IF NOT EXISTS analysis_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_username TEXT NOT NULL,
                status TEXT NOT NULL,
                time_limit_ms INTEGER NOT NULL,
                total_moves INTEGER NOT NULL DEFAULT 0,
                completed_moves INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS analysis_job_moves (
                job_id INTEGER NOT NULL,
                move_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY(job_id, move_id),
                FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(move_id) REFERENCES moves(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_fen_key ON moves(fen_key);
            CREATE INDEX IF NOT EXISTS idx_games_player_date
                ON games(player_username, date);
            CREATE INDEX IF NOT EXISTS idx_job_moves_status
                ON analysis_job_moves(job_id, status);
            """
        )
        ensure_column(conn, "games", "link", "TEXT")
        ensure_column(conn, "games", "player_username", "TEXT")
        ensure_column(conn, "games", "player_color", "TEXT")
        ensure_column(conn, "games", "source_id", "TEXT")
        ensure_column(conn, "games", "provider", "TEXT")
        ensure_column(conn, "games", "time_control", "TEXT")
        ensure_column(conn, "games", "time_class", "TEXT")
        ensure_column(conn, "moves", "is_player_move", "INTEGER")
        ensure_column(conn, "moves", "best_line", "TEXT")
        ensure_column(conn, "moves", "reply_line", "TEXT")
        ensure_column(conn, "moves", "analysis_time_ms", "INTEGER")
        ensure_column(conn, "moves", "analyzed_at", "TEXT")
        ensure_column(conn, "moves", "analysis_depth", "INTEGER")
        ensure_column(conn, "analysis_jobs", "accounts_json", "TEXT")
        ensure_column(conn, "analysis_jobs", "depth", "INTEGER")
        ensure_column(conn, "analysis_jobs", "threads", "INTEGER")
        ensure_column(conn, "analysis_jobs", "run_started_completed", "INTEGER DEFAULT 0")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_games_source_id "
            "ON games(source_id) WHERE source_id IS NOT NULL"
        )
        conn.execute(
            """
            UPDATE OR IGNORE games
            SET source_id = link
            WHERE source_id IS NULL AND link IS NOT NULL AND link != ''
            """
        )
        conn.execute(
            """
            UPDATE games
            SET provider = CASE
                WHEN lower(COALESCE(link, site, '')) LIKE '%lichess.org%' THEN 'lichess'
                ELSE 'chesscom'
            END
            WHERE provider IS NULL
            """
        )
        conn.execute(
            """
            UPDATE games
            SET time_control = COALESCE(NULLIF(time_control, ''), NULL)
            """
        )
        rows = conn.execute(
            """
            SELECT id, event, time_control
            FROM games
            WHERE time_class IS NULL OR time_class = ''
            """
        ).fetchall()
        conn.executemany(
            "UPDATE games SET time_class = ? WHERE id = ?",
            [
                (
                    classify_time_control(row["time_control"], row["event"]),
                    row["id"],
                )
                for row in rows
            ],
        )
        conn.execute(
            """
            WITH completed_depths AS (
                SELECT jm.move_id, MAX(j.depth) AS depth
                FROM analysis_job_moves jm
                JOIN analysis_jobs j ON j.id = jm.job_id
                WHERE jm.status = 'completed' AND j.depth IS NOT NULL
                GROUP BY jm.move_id
            )
            UPDATE moves
            SET analysis_depth = (
                SELECT depth FROM completed_depths
                WHERE completed_depths.move_id = moves.id
            )
            WHERE analysis_depth IS NULL
              AND analyzed_at IS NOT NULL
              AND id IN (SELECT move_id FROM completed_depths)
            """
        )


def normalize_fen(fen):
    return " ".join(fen.split(" ")[:4])


def player_color(headers, username):
    target = username.casefold()
    if (headers.get("White") or "").casefold() == target:
        return "white"
    if (headers.get("Black") or "").casefold() == target:
        return "black"
    return None


def classify_time_control(time_control, event=None):
    event_text = (event or "").casefold()
    for value in ("bullet", "blitz", "rapid", "daily", "correspondence"):
        if value in event_text:
            return "daily" if value == "correspondence" else value

    control = (time_control or "").strip()
    if not control or control == "-":
        return "unknown"
    if "/" in control:
        return "daily"

    first = control.split(":", 1)[0]
    base_text, _, increment_text = first.partition("+")
    try:
        base_seconds = int(base_text)
        increment_seconds = int(increment_text or "0")
    except ValueError:
        return "unknown"

    estimated_seconds = base_seconds + (40 * increment_seconds)
    if estimated_seconds < 180:
        return "bullet"
    if estimated_seconds < 600:
        return "blitz"
    if estimated_seconds < 3600:
        return "rapid"
    return "daily"


def game_source_id(game):
    link = game.headers.get("Link") or game.headers.get("Site")
    if link and link.startswith("http"):
        return link
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return hashlib.sha256(game.accept(exporter).encode("utf-8")).hexdigest()


def save_game(conn, game, username, provider):
    source_id = game_source_id(game)
    existing = conn.execute(
        "SELECT id FROM games WHERE source_id = ?", (source_id,)
    ).fetchone()
    if existing:
        return False, existing["id"], 0, [], []

    headers = game.headers
    color = player_color(headers, username)
    time_control = headers.get("TimeControl")
    time_class = (headers.get("TimeClass") or classify_time_control(
        time_control,
        headers.get("Event"),
    )).strip().lower()
    cursor = conn.execute(
        """
        INSERT INTO games (
            white, black, result, date, event, site, round, link,
            player_username, player_color, source_id, provider,
            time_control, time_class
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            headers.get("White"),
            headers.get("Black"),
            headers.get("Result"),
            headers.get("Date"),
            headers.get("Event"),
            headers.get("Site"),
            headers.get("Round"),
            headers.get("Link"),
            username,
            color,
            source_id,
            provider,
            time_control,
            time_class,
        ),
    )
    game_id = cursor.lastrowid
    board = game.board()
    move_count = 0
    move_ids = []
    player_move_ids = []

    for ply, move in enumerate(game.mainline_moves(), start=1):
        fen_before = board.fen()
        turn = "white" if board.turn else "black"
        san = board.san(move)
        is_player_move = None if color is None else int(turn == color)
        board.push(move)
        move_cursor = conn.execute(
            """
            INSERT INTO moves (
                game_id, ply, move_number, turn, fen_before, fen_key,
                move, san, fen_after, is_player_move
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                ply,
                (ply + 1) // 2,
                turn,
                fen_before,
                normalize_fen(fen_before),
                move.uci(),
                san,
                board.fen(),
                is_player_move,
            ),
        )
        move_ids.append(move_cursor.lastrowid)
        if is_player_move == 1:
            player_move_ids.append(move_cursor.lastrowid)
        move_count += 1

    return True, game_id, move_count, move_ids, player_move_ids


def game_is_before(game, cutoff_date):
    if not cutoff_date:
        return False
    game_date = (game.headers.get("Date") or "").replace(".", "-")
    return bool(game_date and game_date < cutoff_date)


def normalize_game_date(value):
    cleaned = (value or "").replace(".", "-")
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def import_pgn(pgn_text, username, provider="manual", cutoff_date=None):
    stream = io.StringIO(pgn_text)
    added_games = 0
    added_moves = 0
    skipped_games = 0
    move_ids = []
    player_move_ids = []

    with connect() as conn:
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            if game_is_before(game, cutoff_date):
                continue
            added, _, move_count, added_move_ids, added_player_moves = save_game(
                conn, game, username, provider
            )
            if added:
                added_games += 1
                added_moves += move_count
                move_ids.extend(added_move_ids)
                player_move_ids.extend(added_player_moves)
            else:
                skipped_games += 1

    return {
        "added_games": added_games,
        "added_moves": added_moves,
        "skipped_games": skipped_games,
        "move_ids": move_ids,
        "player_move_ids": player_move_ids,
    }


def count_new_pgn_games(pgn_text, cutoff_date=None):
    stream = io.StringIO(pgn_text)
    source_ids = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if game_is_before(game, cutoff_date):
            continue
        source_ids.append(game_source_id(game))

    if not source_ids:
        return 0

    with connect() as conn:
        existing = set()
        for start in range(0, len(source_ids), 500):
            batch = source_ids[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT source_id FROM games WHERE source_id IN ({placeholders})",
                batch,
            ).fetchall()
            existing.update(row["source_id"] for row in rows)
    return sum(source_id not in existing for source_id in source_ids)


def prune_games_before(accounts, cutoff_date):
    if not cutoff_date:
        return {"deleted_games": 0, "deleted_moves": 0}

    clauses = []
    params = []
    for account in accounts:
        clauses.append("(provider = ? AND lower(player_username) = lower(?))")
        params.extend([account["provider"], account["username"]])
    if not clauses:
        return {"deleted_games": 0, "deleted_moves": 0}

    account_sql = " OR ".join(clauses)
    cutoff_sql = "date IS NOT NULL AND date != '' AND replace(date, '.', '-') < ?"
    game_where = f"({account_sql}) AND {cutoff_sql}"
    query_params = [*params, cutoff_date]

    with connect() as conn:
        deleted_games = conn.execute(
            f"SELECT COUNT(*) AS count FROM games WHERE {game_where}",
            query_params,
        ).fetchone()["count"]
        deleted_moves = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM moves
            WHERE game_id IN (SELECT id FROM games WHERE {game_where})
            """,
            query_params,
        ).fetchone()["count"]
        conn.execute(
            f"""
            DELETE FROM analysis_job_moves
            WHERE move_id IN (
                SELECT id FROM moves
                WHERE game_id IN (SELECT id FROM games WHERE {game_where})
            )
            """,
            query_params,
        )
        conn.execute(
            f"""
            DELETE FROM moves
            WHERE game_id IN (SELECT id FROM games WHERE {game_where})
            """,
            query_params,
        )
        conn.execute(f"DELETE FROM games WHERE {game_where}", query_params)
        conn.execute(
            """
            UPDATE analysis_jobs
            SET total_moves = (
                    SELECT COUNT(*)
                    FROM analysis_job_moves
                    WHERE job_id = analysis_jobs.id
                ),
                completed_moves = (
                    SELECT COUNT(*)
                    FROM analysis_job_moves
                    WHERE job_id = analysis_jobs.id AND status = 'completed'
                )
            """
        )
        conn.execute(
            """
            DELETE FROM analysis_jobs
            WHERE NOT EXISTS (
                SELECT 1 FROM analysis_job_moves
                WHERE job_id = analysis_jobs.id
            )
            """
        )

    return {"deleted_games": deleted_games, "deleted_moves": deleted_moves}


def active_analysis_jobs():
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM analysis_jobs
            WHERE status IN ('queued', 'running')
            """
        ).fetchone()
    return row["count"] or 0


def has_analysis_results():
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                EXISTS(
                    SELECT 1
                    FROM moves
                    WHERE COALESCE(analysis_depth, 0) > 0
                       OR analyzed_at IS NOT NULL
                       OR best_move IS NOT NULL
                )
                OR EXISTS(
                    SELECT 1
                    FROM analysis_jobs
                    WHERE status = 'completed'
                      AND completed_moves > 0
                ) AS available
            """
        ).fetchone()
    return bool(row["available"])


def reset_database():
    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM games) AS games,
                (SELECT COUNT(*) FROM moves) AS moves,
                (SELECT COUNT(*) FROM analysis_jobs) AS jobs
            """
        ).fetchone()
        conn.execute("DELETE FROM analysis_job_moves")
        conn.execute("DELETE FROM analysis_jobs")
        conn.execute("DELETE FROM moves")
        conn.execute("DELETE FROM games")
        conn.execute(
            """
            DELETE FROM sqlite_sequence
            WHERE name IN ('games', 'moves', 'analysis_jobs')
            """
        )
    return {
        "deleted_games": counts["games"] or 0,
        "deleted_moves": counts["moves"] or 0,
        "deleted_jobs": counts["jobs"] or 0,
    }


def player_summary(username, provider=None):
    with connect() as conn:
        provider_clause = "AND g.provider = ?" if provider else ""
        params = (username, provider) if provider else (username,)
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT g.id) AS games, COUNT(m.id) AS moves,
                   SUM(CASE WHEN m.is_player_move = 1 THEN 1 ELSE 0 END) AS player_moves
            FROM games g
            LEFT JOIN moves m ON m.game_id = g.id
            WHERE lower(g.player_username) = lower(?)
            {provider_clause}
            """,
            params,
        ).fetchone()
    return {
        "username": username,
        "provider": provider,
        "games": row["games"] or 0,
        "moves": row["moves"] or 0,
        "player_moves": row["player_moves"] or 0,
    }


def latest_game_date(username, provider):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT date
            FROM games
            WHERE provider = ? AND lower(player_username) = lower(?)
              AND date IS NOT NULL AND date != ''
            """,
            (provider, username),
        ).fetchall()
    dates = [
        normalized
        for row in rows
        if (normalized := normalize_game_date(row["date"]))
    ]
    return max(dates) if dates else None
