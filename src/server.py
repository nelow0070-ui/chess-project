from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../db/chess.db")

# HTML 폴더 (index.html 위치)
HTML_DIR = os.path.join(BASE_DIR, "templates")

def normalize_fen(fen):
    return " ".join(fen.split(" ")[:4])

# ---------------- 메인 페이지 ----------------
@app.route("/")
def index():
    return send_from_directory(HTML_DIR, "index.html")

# ---------------- API ----------------
@app.route("/moves")
def get_moves():
    fen = request.args.get("fen")

    if not fen:
        return jsonify([])

    fen_key = normalize_fen(fen)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT move, san, mistake_type, COUNT(*) as cnt
        FROM moves
        WHERE fen_key = ?
        GROUP BY move
        ORDER BY cnt DESC
    """, (fen_key,))

    rows = cur.fetchall()
    conn.close()

    result = []
    for move, san, mistake, cnt in rows:
        result.append({
            "uci": move,
            "san": san,
            "type": mistake if mistake else "unknown",
            "count": cnt
        })

    return jsonify(result)

# ---------------- 서버 실행 ----------------
if __name__ == "__main__":
    app.run(debug=True)