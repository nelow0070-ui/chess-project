from flask import Flask, request, jsonify, send_from_directory
import chess
import chess.engine
import sqlite3
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../db/chess.db")
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")
EVAL_DEPTH = int(os.environ.get("EVAL_DEPTH", "10"))

# HTML 폴더 (index.html 위치)
HTML_DIR = os.path.join(BASE_DIR, "templates")

def normalize_fen(fen):
    return " ".join(fen.split(" ")[:4])

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
        return {
            "type": "mate",
            "mate": white_score.mate()
        }

    return {
        "type": "cp",
        "cp": white_score.score()
    }

# ---------------- 메인 페이지 ----------------
@app.route("/")
def index():
    return send_from_directory(HTML_DIR, "index.html")

# ---------------- API ----------------
@app.route("/moves")
def get_moves():
    fen = request.args.get("fen")
    perspective = request.args.get("perspective")
    player_username = request.args.get("player", "Nelo_w")

    if not fen:
        return jsonify([])

    fen_keys = fen_lookup_keys(fen)
    placeholders = ",".join("?" for _ in fen_keys)
    where_clauses = [f"m.fen_key IN ({placeholders})"]
    params = list(fen_keys)

    if player_username:
        where_clauses.append("lower(g.player_username) = lower(?)")
        params.append(player_username)

    if perspective == "player":
        where_clauses.append("m.is_player_move = 1")
    elif perspective == "opponent":
        where_clauses.append("m.is_player_move = 0")

    where_sql = " AND ".join(where_clauses)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(f"""
        SELECT m.move, m.san, m.mistake_type, m.turn, g.result, m.is_player_move
        FROM moves m
        JOIN games g ON g.id = m.game_id
        WHERE {where_sql}
    """, params)

    rows = cur.fetchall()
    conn.close()

    grouped = {}
    for move, san, mistake, turn, game_result, is_player_move in rows:
        key = (move, san)
        item = grouped.setdefault(key, {
            "uci": move,
            "san": san,
            "turn": turn,
            "is_player_move": is_player_move,
            "count": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "types": {}
        })

        item["count"] += 1
        mistake_key = mistake if mistake else "unknown"
        item["types"][mistake_key] = item["types"].get(mistake_key, 0) + 1

        if game_result == "1/2-1/2":
            item["draws"] += 1
        elif (turn == "white" and game_result == "1-0") or (turn == "black" and game_result == "0-1"):
            item["wins"] += 1
        elif game_result in ("1-0", "0-1"):
            item["losses"] += 1

    result = []
    for item in grouped.values():
        decisive_score = item["wins"] + (item["draws"] * 0.5)
        item["winrate"] = round((decisive_score / item["count"]) * 100, 1) if item["count"] else None
        item["type"] = max(item["types"].items(), key=lambda pair: pair[1])[0]
        result.append({
            "uci": item["uci"],
            "san": item["san"],
            "type": item["type"],
            "count": item["count"],
            "winrate": item["winrate"],
            "wins": item["wins"],
            "draws": item["draws"],
            "losses": item["losses"],
            "turn": item["turn"],
            "is_player_move": item["is_player_move"]
        })

    result.sort(key=lambda item: item["count"], reverse=True)
    return jsonify(result)


@app.route("/eval")
def get_eval():
    fen = request.args.get("fen")

    if not fen:
        return jsonify({"error": "fen is required"}), 400

    try:
        board = chess.Board(fen)
    except ValueError:
        return jsonify({"error": "invalid fen"}), 400

    engine = None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        info = engine.analyse(board, chess.engine.Limit(depth=EVAL_DEPTH))
        evaluation = score_to_eval(info["score"])
        return jsonify(evaluation)
    except FileNotFoundError:
        return jsonify({"error": "stockfish not found"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if engine:
            engine.quit()

# ---------------- 서버 실행 ----------------
if __name__ == "__main__":
    app.run(debug=True)