# checkss

Chess.com 또는 Lichess 게임을 가져오고 Stockfish 분석을 백그라운드 작업으로 처리하는 웹 앱입니다.

## 사용자 흐름

1. 첫 페이지에서 Chess.com과 Lichess 계정을 각각 연결
2. 두 번째 페이지에서 보관 시작 날짜, Stockfish 깊이와 CPU 코어 수 선택
3. 세 번째 페이지에서 분석 진행률 확인, 중단 또는 이어하기
4. 완료 표시의 `보드로 이동`을 누른 뒤 보드 검색 페이지에서 클릭 방식 체스보드와 저장된 수 조회

첫 분석이 완료되면 자동 이동하지 않고 완료 표시와 `보드로 이동` 버튼을 보여줍니다.
계정 연결과 분석 화면은 여백을 줄이고, 작고 단순한 진행 표시를 사용합니다.
계정 연결 화면은 플랫폼에서 보드와 데이터베이스로 기보가 모이는 이미지 일러스트를 보여주고,
분석 화면은 안경 쓴 Stockfish 물고기와 함께 폰이 진행 바 위를 걸어가 마지막에 퀸으로 승급하는 진행 표현을 사용합니다.
보드 화면은 세로 여백을 줄이도록 보드를 키우고, FEN/PGN 도구를 오른쪽 패널 하단에 배치합니다.
보드의 게임 추가 버튼은 계정 추가, 분석 설정, 분석, 완료 단계 흐름으로 돌아갑니다.
계정 연결부터 분석 진행까지는 같은 프레임 안에서 콘텐츠만 슬라이드됩니다.

분석 작업과 대상 수는 SQLite에 저장됩니다. 서버가 재시작되면 진행 중이던 작업은 대기 상태로 돌아가 자동 재개됩니다.

## Stockfish 성능

Windows에서는 AVX-VNNI를 지원하면 해당 Stockfish 18 빌드를 우선 사용하고,
실행할 수 없으면 AVX2 빌드를 사용합니다. 분석은 한 엔진의 스레드 수를 늘리는
대신 여러 1스레드 엔진에 고유 포지션을 분배합니다. 동일 포지션은 작업 내에서
한 번만 계산합니다.

1.1.20의 기본 분석 설정은 깊이 14와 병렬 작업자 6개입니다. 6게임 277수를
깊이 16 결과와 비교한 실측에서 병렬 깊이 14는 기존 순차 깊이 12보다 약 3배
빠르면서 추천 수 일치율이 1.08%p 높았습니다. 실제 작업자 수는 CPU와 분석할
포지션 수에 맞춰 자동 제한됩니다.

저장된 Lichess 게임으로 성능과 정확도를 다시 측정하려면 다음 명령을 사용합니다.

```powershell
.\venv\Scripts\python.exe tools\benchmark_stockfish.py --baseline --depth 12
.\venv\Scripts\python.exe tools\benchmark_accuracy.py --candidate-depth 14 --reference-depth 16 --workers 6
```

## Windows 로컬 실행

```powershell
.\run.ps1
```

스크립트가 가상환경, Python 패키지, Stockfish를 준비한 뒤 서버를 실행합니다.
PowerShell 실행 정책으로 막히면 `run.bat`을 더블클릭하거나 다음 명령을 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

서버 실행 후 `http://127.0.0.1:5000`으로 접속합니다. `main.py`는 게임 수집 전용이며 서버를 실행하지 않습니다.

## 게임 수집 CLI

```powershell
.\venv\Scripts\python.exe src\main.py chesscom Nelo_w
.\venv\Scripts\python.exe src\main.py lichess 사용자아이디
```

`main.py`는 게임 수집과 DB 저장만 담당합니다. 이미 저장된 게임은 다시 추가하지 않습니다.

## Windows 설치 프로그램 빌드

개발 PC에 Inno Setup 6을 설치한 뒤 다음 명령을 실행합니다.

```powershell
.\build-installer.ps1
```

빌드 결과는 `release\checkss-Setup-1.1.20.exe`입니다. 설치 사용자는 Python
또는 Stockfish를 별도로 설치할 필요가 없습니다.

설치형 앱의 사용자 데이터는 `%LOCALAPPDATA%\checkss\chess.db`에 저장되므로
앱 업데이트나 재설치 후에도 유지됩니다. 앱 제거 시에도 사용자 데이터는 자동으로
삭제하지 않습니다.

실행하면 주소창 없는 checkss 앱 창이 자동으로 열리고 checkss는 Windows 알림 영역에서 계속
실행됩니다. Edge 또는 Chrome 앱 창을 열 수 없는 환경에서는 기본 브라우저로 열립니다.
종료하려면 알림 영역의 checkss 아이콘을 우클릭하고 `종료`를
선택합니다.

## 백그라운드 생명주기 검증

실제 Stockfish로 중단 직후 이어하기, 엔진 프로세스 종료, 계산 중 앱 종료 후
자동 재개, 반복 분석 메모리 변화를 한 번에 확인할 수 있습니다.

```powershell
.\venv\Scripts\python.exe tools\verify_background_lifecycle.py
```
