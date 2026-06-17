import sqlite3
import chess
import chess.engine
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../db/chess.db")

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")

# ---------------- 설정 ----------------
DEPTH = 10  # 처음엔 8~10 추천
SLEEP = 0   # 너무 빠르면 0.01 정도 주기

# ---------------- 실수 분류 ----------------
def classify(diff):
    if diff is None:
        return "unknown"
    if diff < 50:
        return "best"
    elif diff < 150:
        return "inaccuracy"
    elif diff < 300:
        return "mistake"
    else:
        return "blunder"

# ---------------- 점수 변환 ----------------
def get_cp_score(score):
    if score.is_mate():
        # mate는 매우 큰 값으로 처리
        return 10000 if score.mate() > 0 else -10000
    return score.score()

# ---------------- 핵심 분석 ----------------
def analyze_position(engine, fen, move_uci):
    board = chess.Board(fen)
    mover = board.turn

    # 현재 포지션 평가
    info_before = engine.analyse(board, chess.engine.Limit(depth=DEPTH))
    score_before = get_cp_score(info_before["score"].relative)

    # 최선수
    result = engine.play(board, chess.engine.Limit(depth=DEPTH))
    best_move = result.move.uci()

    # 실제 수 적용
    move = chess.Move.from_uci(move_uci)
    if move not in board.legal_moves:
        return best_move, None, "illegal"

    board.push(move)

    # 이후 평가
    info_after = engine.analyse(board, chess.engine.Limit(depth=DEPTH))
    score_after = get_cp_score(info_after["score"].relative)
    if board.turn != mover and score_after is not None:
        score_after = -score_after

    # 점수 차이
    diff = score_before - score_after if score_before is not None and score_after is not None else None

    return best_move, diff, classify(diff)

# ---------------- 전체 분석 ----------------
def analyze_all():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    cur.execute("""
        SELECT id, fen_before, move
        FROM moves
    """)

    rows = cur.fetchall()
    total = len(rows)

    print(f"총 {total} 수 분석 시작\n")

    start_time = time.time()

    for i, (move_id, fen, move_uci) in enumerate(rows, start=1):
        try:
            best_move, diff, mistake = analyze_position(engine, fen, move_uci)

            cur.execute("""
                UPDATE moves
                SET best_move=?, eval_diff=?, mistake_type=?
                WHERE id=?
            """, (best_move, diff, mistake, move_id))

            # 진행 상황 출력
            if i % 50 == 0 or i == total:
                elapsed = time.time() - start_time
                print(f"[{i}/{total}] 진행중... ({elapsed:.1f}s)")

            if SLEEP > 0:
                time.sleep(SLEEP)

        except Exception as e:
            print(f"❌ 오류 (id={move_id}):", e)

    conn.commit()
    conn.close()
    engine.quit()

    print("\n✅ 전체 분석 완료")

# ---------------- 실행 ----------------
if __name__ == "__main__":
    analyze_all()
