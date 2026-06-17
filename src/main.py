import io

import chess.pgn

from save_games import (
    download_chesscom_all,
    init_db,
    parse_pgn_text,
    save_game_to_db,
)

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

            if line == "" and lines and lines[-1] == "":
                break

            lines.append(line)

        pgn_text = "\n".join(lines).strip()

        if not pgn_text:
            print("빈 PGN\n")
            continue

        game = chess.pgn.read_game(io.StringIO(pgn_text))

        if game is None:
            print("PGN 파싱 실패\n")
            continue

        save_game_to_db(game)
        print("저장 완료!\n")

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
            print("게임을 가져오지 못했습니다.")
        else:
            parse_pgn_text(pgn_text, player_username=username)

    else:
        print("잘못된 입력")
