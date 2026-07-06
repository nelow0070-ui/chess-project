import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
APP_VERSION = "1.1.19"
DEFAULT_ANALYSIS_DEPTH = 14
DEFAULT_ANALYSIS_WORKERS = 6


def application_data_dir():
    configured = os.environ.get("CHECKSS_DATA_DIR") or os.environ.get("CHESS_DATA_DIR")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "checkss"
        return Path.home() / "AppData" / "Local" / "checkss"
    return PROJECT_DIR / "db"


DATA_DIR = application_data_dir()
DB_PATH = Path(
    os.environ.get("CHECKSS_DB_PATH")
    or os.environ.get("CHESS_DB_PATH")
    or DATA_DIR / "chess.db"
)


def bundled_path(*parts):
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = PROJECT_DIR
    return root.joinpath(*parts)


def stockfish_candidates():
    configured = os.environ.get("STOCKFISH_PATH")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            bundled_path("stockfish", "stockfish-windows-x86-64-avxvnni.exe"),
            PROJECT_DIR
            / "tools"
            / "stockfish-avxvnni"
            / "stockfish"
            / "stockfish-windows-x86-64-avxvnni.exe",
            bundled_path("stockfish", "stockfish-windows-x86-64-avx2.exe"),
            PROJECT_DIR
            / "tools"
            / "stockfish"
            / "stockfish"
            / "stockfish-windows-x86-64-avx2.exe",
            PROJECT_DIR / "tools" / "stockfish" / "stockfish.exe",
            Path("/usr/games/stockfish"),
            Path("/usr/local/bin/stockfish"),
        ]
    )
    found = []
    for candidate in candidates:
        path = str(candidate)
        if candidate.is_file() and path not in found:
            found.append(path)
    return found


def find_stockfish():
    candidates = stockfish_candidates()
    return candidates[0] if candidates else "stockfish"


STOCKFISH_PATH = find_stockfish()
STOCKFISH_FALLBACK_PATHS = [
    path for path in stockfish_candidates() if path != STOCKFISH_PATH
]
STOCKFISH_THREADS = int(
    os.environ.get("STOCKFISH_THREADS", str(DEFAULT_ANALYSIS_WORKERS))
)
STOCKFISH_HASH_MB = int(os.environ.get("STOCKFISH_HASH_MB", "256"))
STOCKFISH_POPEN_ARGS = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32"
    else {}
)
