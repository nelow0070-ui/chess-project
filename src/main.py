import sqlite3
import chess.pgn
import io
import os
import requests
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../db/chess.db")

# ---------------- DB 초기화 ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        white TEXT,
        black TEXT,
        result TEXT,
        date TEXT,
        event TEXT,
        site TEXT,
        round TEXT,
        eco TEXT,
        opening TEXT
    );

    CREATE TABLE IF NOT EXISTS moves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        ply INTEGER,
        move_number INTEGER,
        turn TEXT,
        uci TEXT,
        san TEXT,
        fen TEXT,
        evaluation REAL,
        best_move TEXT,
        mistake_level TEXT,
        FOREIGN KEY(game_id) REFERENCES games(id)
    );
    """)

    conn.commit()
    conn.close()

# ---------------- 게임 저장 ----------------
def save_game_to_db(game):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    headers = game.headers

    cur.execute("""
    INSERT INTO games (white, black, result, date, event, site, round)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        headers.get("White"),
        headers.get("Black"),
        headers.get("Result"),
        headers.get("Date"),
        headers.get("Event"),
        headers.get("Site"),
        headers.get("Round"),
    ))

    game_id = cur.lastrowid

    board = game.board()
    ply = 1
    move_number = 1

    for move in game.mainline_moves():
        san = board.san(move)
        uci = move.uci()
        turn = "white" if board.turn else "black"

        board.push(move)
        fen = board.fen()

        cur.execute("""
        INSERT INTO moves (
            game_id, ply, move_number, turn,
            uci, san, fen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id,
            ply,
            move_number,
            turn,
            uci,
            san,
            fen
        ))

        if turn == "black":
            move_number += 1

        ply += 1

    conn.commit()
    conn.close()

# ---------------- PGN 파싱 ----------------
def parse_pgn_text(pgn_text):
    pgn_io = io.StringIO(pgn_text)

    count = 0
    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break
        save_game_to_db(game)
        count += 1

    print(f"총 {count} 게임 저장 완료")

# ---------------- Chess.com API ----------------
def download_chesscom_pgn(username, year, month):
    url = f"https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(url, headers=headers)
    except Exception as e:
        print("❌ 네트워크 오류:", e)
        return None

    print(f"[{year}-{month:02d}] STATUS:", response.status_code)

    if response.status_code != 200:
        print("❌ 요청 실패")
        return None

    data = response.json()
    games = data.get("games", [])

    if not games:
        print("⚠️ 게임 없음")
        return None

    pgn_list = [g["pgn"] for g in games if "pgn" in g]
    return "\n\n".join(pgn_list)

def download_chesscom_all(username, year):
    all_pgn = ""

    for month in range(1, 13):
        print(f"\n📥 {year}-{month:02d} 가져오는 중...")
        pgn = download_chesscom_pgn(username, year, month)

        if pgn:
            all_pgn += pgn + "\n\n"

        time.sleep(1)  # rate limit 방지

    return all_pgn

# ---------------- 입력 모드 ----------------
def input_pgn_mode():
    print("\nPGN 입력 모드 (exit 입력 시 종료)\n")

    while True:
        print("PGN 입력 시작 (빈 줄 2번 입력하면 종료):")

        lines = []

        while True:
            line = input()

            if line.strip().lower() == "exit":
                print("종료합니다.")
                return

            if line == "":
                if lines and lines[-1] == "":
                    break

            lines.append(line)

        pgn_text = "\n".join(lines).strip()

        if not pgn_text:
            print("⚠️ 빈 PGN\n")
            continue

        game = chess.pgn.read_game(io.StringIO(pgn_text))

        if game is None:
            print("❌ PGN 파싱 실패\n")
            continue

        save_game_to_db(game)
        print("✅ 저장 완료!\n")

# ---------------- 실행 ----------------
if __name__ == "__main__":
    init_db()

    print("\n모드 선택:")
    print("1. PGN 파일")
    print("2. 직접 입력")
    print("3. Chess.com 자동 가져오기")

    mode = input("선택: ")

    if mode == "1":
        path = input("PGN 파일 경로 입력: ")
        with open(path, encoding="utf-8") as f:
            parse_pgn_text(f.read())

    elif mode == "2":
        input_pgn_mode()

    elif mode == "3":
        username = input("Chess.com 아이디 입력: ")
        year = int(input("연도 입력 (예: 2025): "))

        pgn_text = download_chesscom_all(username, year)

        if not pgn_text:
            print("❌ 게임을 가져오지 못했습니다.")
        else:
            parse_pgn_text(pgn_text)

    else:
        print("❌ 잘못된 입력")