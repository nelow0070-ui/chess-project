import subprocess

# stockfish 실행
engine = subprocess.Popen(
    ["stockfish"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True
)

def send(cmd):
    engine.stdin.write(cmd + "\n")
    engine.stdin.flush()

def get():
    return engine.stdout.readline().strip()

# UCI 초기화
send("uci")
while True:
    if get() == "uciok":
        break

# 새 게임 시작
send("ucinewgame")

# 시작 포지션
send("position startpos")

# 엔진 계산
send("go depth 10")

# bestmove 받을 때까지 읽기
while True:
    line = get()
    if line.startswith("bestmove"):
        print("엔진 수:", line)
        break

# 종료
send("quit")