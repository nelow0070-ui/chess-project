"""Legacy-compatible imports for older scripts.

New code should import from database.py and chesscom.py directly.
"""

from chesscom import import_player_games
from database import import_pgn, init_db, save_game
from lichess import import_player_games as import_lichess_games


__all__ = [
    "import_pgn",
    "import_player_games",
    "import_lichess_games",
    "init_db",
    "save_game",
]
