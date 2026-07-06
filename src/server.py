from pathlib import Path
from collections import defaultdict, deque
import os
import sys
import time

import chess
import chess.engine
from flask import Flask, jsonify, redirect, render_template, request, url_for

from analysis_service import (
    active_job_id,
    account_where,
    cancel_job,
    create_job,
    estimate_seconds,
    job_payload,
    latest_completed_settings,
    normalize_accounts,
    queue_missing_opponent_moves,
    resume_job,
    worker,
)
from chesscom import (
    ChessComError,
    fetch_player_pgn as fetch_chesscom_pgn,
    import_player_games as import_chesscom_games,
)
from config import (
    APP_VERSION,
    DEFAULT_ANALYSIS_DEPTH,
    DEFAULT_ANALYSIS_WORKERS,
    STOCKFISH_PATH,
    STOCKFISH_POPEN_ARGS,
)
from database import (
    active_analysis_jobs,
    connect,
    count_new_pgn_games,
    has_analysis_results,
    import_pgn,
    init_db,
    player_summary,
    prune_games_before,
    reset_database,
)
from lichess import (
    LichessError,
    fetch_player_pgn as fetch_lichess_pgn,
    import_player_games as import_lichess_games,
)


BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR.parent))
app = Flask(
    __name__,
    template_folder=str(
        RESOURCE_DIR / "templates"
        if getattr(sys, "frozen", False)
        else BASE_DIR / "templates"
    ),
    static_folder=str(
        RESOURCE_DIR / "static"
        if getattr(sys, "frozen", False)
        else BASE_DIR.parent / "static"
    ),
    static_url_path="/static",
)

IMPORTERS = {
    "chesscom": (import_chesscom_games, ChessComError),
    "lichess": (import_lichess_games, LichessError),
}
FETCHERS = {
    "chesscom": (fetch_chesscom_pgn, ChessComError),
    "lichess": (fetch_lichess_pgn, LichessError),
}
EVAL_FEN_MAX_LENGTH = 120
EVAL_RATE_LIMIT_REQUESTS = 60
EVAL_RATE_LIMIT_WINDOW_SECONDS = 60
eval_request_times = defaultdict(deque)

init_db()
if (
    os.environ.get("CHECKSS_DISABLE_WORKER")
    or os.environ.get("CHESS_DISABLE_WORKER")
) != "1":
    queue_missing_opponent_moves()
    worker.resume()


def fen_lookup_keys(fen):
    parts = fen.split(" ")
    if len(parts) < 4:
        return [fen]
    exact_key = " ".join(parts[:4])
    no_ep_key = " ".join(parts[:3] + ["-"])
    return list(dict.fromkeys([exact_key, no_ep_key]))


def score_to_eval(score):
    white_score = score.white()
    if white_score.is_mate():
        return {"type": "mate", "mate": white_score.mate()}
    return {"type": "cp", "cp": white_score.score()}


def eval_rate_limited(client_id):
    now = time.monotonic()
    timestamps = eval_request_times[client_id or "local"]
    while timestamps and now - timestamps[0] > EVAL_RATE_LIMIT_WINDOW_SECONDS:
        timestamps.popleft()
    if len(timestamps) >= EVAL_RATE_LIMIT_REQUESTS:
        return True
    timestamps.append(now)
    return False


@app.get("/")
def index():
    if request.args.get("flow") == "add-games":
        return render_template("accounts.html", flow_mode="add-games")
    if active_analysis_jobs():
        return redirect(url_for("analyzing"))
    if has_analysis_results():
        return redirect(url_for("board"))
    return render_template("accounts.html", flow_mode="setup")


@app.get("/api/health")
def health():
    return jsonify({"app": "checkss", "status": "ok", "version": APP_VERSION})


@app.get("/analysis")
def analysis_setup():
    if active_analysis_jobs():
        return redirect(url_for("analyzing"))
    return render_template("analysis.html")


@app.get("/analyzing")
def analyzing():
    return render_template("analyzing.html")


@app.get("/complete")
def complete():
    return render_template("complete.html")


@app.get("/board")
def board():
    return render_template("board.html")


@app.get("/legacy")
def legacy():
    return redirect(url_for("board"))


@app.post("/api/import")
def import_games():
    payload = request.get_json(silent=True) or {}
    provider = (payload.get("provider") or "").strip().lower()
    username = (payload.get("username") or "").strip()
    if provider not in IMPORTERS:
        return jsonify({"error": "지원하지 않는 플랫폼입니다."}), 400
    if not username:
        return jsonify({"error": "아이디를 입력해주세요."}), 400

    importer, error_type = IMPORTERS[provider]
    try:
        imported = importer(username)
    except error_type as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        app.logger.exception("Account import failed")
        return jsonify({"error": "게임을 불러오지 못했습니다. 잠시 후 다시 시도해주세요."}), 500

    canonical = imported["username"]
    imported.pop("move_ids", None)
    imported.pop("player_move_ids", None)
    summary = player_summary(canonical, provider=provider)
    return jsonify({**imported, **summary, "provider": provider})


@app.post("/api/accounts/summary")
def accounts_summary():
    payload = request.get_json(silent=True) or {}
    accounts = normalize_accounts(payload.get("accounts"))
    cutoff_date = (payload.get("cutoff_date") or "").strip()
    depth = max(
        8,
        min(16, int(payload.get("depth") or DEFAULT_ANALYSIS_DEPTH)),
    )
    summaries = [
        player_summary(account["username"], provider=account["provider"])
        for account in accounts
    ]
    eligible_moves = sum(item["moves"] for item in summaries)
    eligible_games = sum(item["games"] for item in summaries)
    if accounts:
        where_sql, params = account_where(accounts)
        date_clause = ""
        query_params = [*params, depth]
        if cutoff_date:
            date_clause = """
              AND (
                g.date IS NULL OR g.date = ''
                OR replace(g.date, '.', '-') >= ?
              )
            """
            query_params.append(cutoff_date)
        with connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT CASE
                           WHEN COALESCE(m.analysis_depth, 0) < ?
                           THEN g.id END) AS games,
                       SUM(CASE
                           WHEN COALESCE(m.analysis_depth, 0) < ?
                           THEN 1 ELSE 0 END) AS analysis_moves
                FROM games g
                LEFT JOIN moves m ON m.game_id = g.id
                WHERE ({where_sql})
                {date_clause}
                """,
                [depth, depth, *params, *([cutoff_date] if cutoff_date else [])],
            ).fetchone()
        eligible_games = row["games"] or 0
        eligible_moves = row["analysis_moves"] or 0
    return jsonify(
        {
            "accounts": summaries,
            "games": sum(item["games"] for item in summaries),
            "moves": sum(item["moves"] for item in summaries),
            "player_moves": sum(item["player_moves"] for item in summaries),
            "eligible_games": eligible_games,
            "eligible_moves": eligible_moves,
            "eligible_player_moves": eligible_moves,
        }
    )


@app.post("/api/database/reset")
def reset_all_data():
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmation") != "RESET":
        return jsonify({"error": "초기화 확인 문구가 올바르지 않습니다."}), 400
    if active_analysis_jobs():
        return jsonify({"error": "진행 중인 분석을 먼저 중단해주세요."}), 409
    return jsonify(reset_database())


@app.post("/api/estimate")
def estimate_analysis():
    payload = request.get_json(silent=True) or {}
    move_count = max(1, int(payload.get("move_count") or 1))
    depth = max(
        8,
        min(16, int(payload.get("depth") or DEFAULT_ANALYSIS_DEPTH)),
    )
    threads = max(
        1,
        min(16, int(payload.get("threads") or DEFAULT_ANALYSIS_WORKERS)),
    )
    return jsonify(
        {
            "move_count": move_count,
            "depth": depth,
            "threads": threads,
            "estimated_seconds": estimate_seconds(move_count, depth, threads),
        }
    )


@app.post("/api/jobs")
def start_analysis():
    payload = request.get_json(silent=True) or {}
    accounts = normalize_accounts(payload.get("accounts"))
    if not accounts:
        return jsonify({"error": "분석할 계정이 없습니다."}), 400
    active_id = active_job_id(accounts)
    if active_id:
        response = job_payload(active_id)
        response["created"] = False
        response["cleanup"] = {"deleted_games": 0, "deleted_moves": 0}
        return jsonify(response)
    cleanup = prune_games_before(accounts, (payload.get("cutoff_date") or "").strip())
    try:
        job_id, created = create_job(
            accounts,
            payload.get("depth") or DEFAULT_ANALYSIS_DEPTH,
            payload.get("threads") or DEFAULT_ANALYSIS_WORKERS,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    response = job_payload(job_id)
    response["created"] = created
    response["cleanup"] = cleanup
    return jsonify(response), 201 if created else 200


@app.get("/api/jobs/<int:job_id>")
def get_job(job_id):
    job = job_payload(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
    return jsonify(job)


@app.post("/api/jobs/active")
def get_active_job():
    payload = request.get_json(silent=True) or {}
    accounts = normalize_accounts(payload.get("accounts"))
    job_id = active_job_id(accounts) if accounts else None
    if not job_id:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM analysis_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        job_id = row["id"] if row else None
    return jsonify({"job": job_payload(job_id) if job_id else None})


@app.post("/api/jobs/<int:job_id>/cancel")
def stop_analysis(job_id):
    if not cancel_job(job_id):
        return jsonify({"error": "중단할 수 있는 작업이 아닙니다."}), 409
    return jsonify(job_payload(job_id))


@app.post("/api/jobs/<int:job_id>/resume")
def continue_analysis(job_id):
    if not resume_job(job_id):
        return jsonify({"error": "이어갈 수 있는 작업이 아닙니다."}), 409
    return jsonify(job_payload(job_id))


def fetch_account_pgn(account):
    fetcher, error_type = FETCHERS[account["provider"]]
    try:
        fetched = fetcher(account["username"])
    except error_type as exc:
        raise RuntimeError(str(exc)) from exc
    if account["provider"] == "chesscom":
        username, pgn_text, _ = fetched
    else:
        username, pgn_text = fetched
    return username, pgn_text


@app.post("/api/updates/check")
def check_updates():
    payload = request.get_json(silent=True) or {}
    accounts = normalize_accounts(payload.get("accounts"))
    cutoff_date = (payload.get("cutoff_date") or "").strip()
    settings = latest_completed_settings(accounts)
    if not settings:
        return jsonify({"available": False, "reason": "no_completed_analysis"})

    updates = []
    try:
        for account in accounts:
            canonical, pgn_text = fetch_account_pgn(account)
            count = count_new_pgn_games(pgn_text, cutoff_date=cutoff_date)
            if count:
                updates.append(
                    {
                        "provider": account["provider"],
                        "username": canonical,
                        "new_games": count,
                    }
                )
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(
        {
            "available": bool(updates),
            "updates": updates,
            "new_games": sum(item["new_games"] for item in updates),
            "settings": settings,
        }
    )


@app.post("/api/updates/apply")
def apply_updates():
    payload = request.get_json(silent=True) or {}
    accounts = normalize_accounts(payload.get("accounts"))
    cutoff_date = (payload.get("cutoff_date") or "").strip()
    settings = latest_completed_settings(accounts)
    if not settings:
        return jsonify({"error": "재사용할 완료 분석 설정이 없습니다."}), 400

    added_games = 0
    added_moves = 0
    move_ids = []
    refreshed_accounts = []
    try:
        for account in accounts:
            canonical, pgn_text = fetch_account_pgn(account)
            result = import_pgn(
                pgn_text,
                canonical,
                provider=account["provider"],
                cutoff_date=cutoff_date,
            )
            added_games += result["added_games"]
            added_moves += result["added_moves"]
            move_ids.extend(result["move_ids"])
            refreshed_accounts.append(
                {"provider": account["provider"], "username": canonical}
            )
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    job = None
    if move_ids:
        job_id, _ = create_job(
            refreshed_accounts,
            settings["depth"],
            settings["threads"],
            move_ids=move_ids,
        )
        job = job_payload(job_id)

    return jsonify(
        {
            "added_games": added_games,
            "added_moves": added_moves,
            "job": job,
            "accounts": [
                player_summary(item["username"], provider=item["provider"])
                for item in refreshed_accounts
            ],
        }
    )


@app.get("/moves")
def get_moves():
    fen = request.args.get("fen")
    perspective = request.args.get("perspective")
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    accounts = normalize_accounts(
        [
            {"provider": "chesscom", "username": request.args.get("chesscom")},
            {"provider": "lichess", "username": request.args.get("lichess")},
        ]
    )
    if not fen:
        return jsonify([])

    fen_keys = fen_lookup_keys(fen)
    placeholders = ",".join("?" for _ in fen_keys)
    where_clauses = [f"m.fen_key IN ({placeholders})"]
    params = list(fen_keys)

    if accounts:
        accounts_sql, accounts_params = account_where(accounts)
        where_clauses.append(f"({accounts_sql})")
        params.extend(accounts_params)
    if perspective == "player":
        where_clauses.append("m.is_player_move = 1")
    elif perspective == "opponent":
        where_clauses.append("m.is_player_move = 0")
    if date_from:
        where_clauses.append(
            "(g.date IS NOT NULL AND g.date != '' "
            "AND replace(g.date, '.', '-') >= ?)"
        )
        params.append(date_from)
    if date_to:
        where_clauses.append(
            "(g.date IS NOT NULL AND g.date != '' "
            "AND replace(g.date, '.', '-') <= ?)"
        )
        params.append(date_to)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT m.move, m.san, m.mistake_type, m.turn,
                   g.result, g.player_color, m.is_player_move
            FROM moves m
            JOIN games g ON g.id = m.game_id
            WHERE {" AND ".join(where_clauses)}
            """,
            params,
        ).fetchall()

    grouped = {}
    for row in rows:
        key = (row["move"], row["san"])
        item = grouped.setdefault(
            key,
            {
                "uci": row["move"],
                "san": row["san"],
                "turn": row["turn"],
                "is_player_move": row["is_player_move"],
                "count": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "types": {},
            },
        )
        item["count"] += 1
        mistake = row["mistake_type"] or "unknown"
        item["types"][mistake] = item["types"].get(mistake, 0) + 1
        if row["result"] == "1/2-1/2":
            item["draws"] += 1
        elif row["result"] in ("1-0", "0-1"):
            player_color = (row["player_color"] or "").lower()
            if player_color == "white":
                player_won = row["result"] == "1-0"
            elif player_color == "black":
                player_won = row["result"] == "0-1"
            else:
                player_won = (row["turn"] == "white" and row["result"] == "1-0") or (
                    row["turn"] == "black" and row["result"] == "0-1"
                )
            if player_won:
                item["wins"] += 1
            else:
                item["losses"] += 1

    result = []
    for item in grouped.values():
        item["winrate"] = round(
            (item["wins"] + item["draws"] * 0.5) / item["count"] * 100, 1
        )
        item["type"] = max(item["types"].items(), key=lambda pair: pair[1])[0]
        item.pop("types")
        result.append(item)
    result.sort(key=lambda item: item["count"], reverse=True)
    return jsonify(result)


@app.get("/eval")
def get_eval():
    fen = request.args.get("fen")
    if not fen:
        return jsonify({"error": "fen is required"}), 400
    if len(fen) > EVAL_FEN_MAX_LENGTH:
        return jsonify({"error": "fen is too long"}), 400
    if eval_rate_limited(request.remote_addr):
        return jsonify({"error": "too many eval requests"}), 429
    try:
        position = chess.Board(fen)
    except ValueError:
        return jsonify({"error": "invalid fen"}), 400

    engine = None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(
            STOCKFISH_PATH,
            **STOCKFISH_POPEN_ARGS,
        )
        info = engine.analyse(position, chess.engine.Limit(time=0.25))
        return jsonify(score_to_eval(info["score"]))
    except FileNotFoundError:
        return jsonify({"error": "stockfish not found"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if engine:
            engine.quit()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("CHECKSS_HOST", "127.0.0.1"),
        port=int(os.environ.get("CHECKSS_PORT", "5000")),
        debug=os.environ.get("CHECKSS_DEBUG") == "1",
        use_reloader=False,
    )
