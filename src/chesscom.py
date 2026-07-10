import requests

from database import import_pgn


API_ROOT = "https://api.chess.com/pub"
HEADERS = {
    "User-Agent": "ChessAnalysisProject/1.0 (local chess analysis app)",
}


class ChessComError(RuntimeError):
    pass


def get_json(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=25)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise ChessComError(f"Chess.com 요청에 실패했습니다: {exc}") from exc


def fetch_player_pgn(username):
    profile = get_json(f"{API_ROOT}/player/{username}")
    canonical_username = profile.get("username") or username
    archives = get_json(f"{API_ROOT}/player/{canonical_username}/games/archives").get(
        "archives", []
    )

    pgn_parts = []
    for archive_url in archives:
        games = get_json(archive_url).get("games", [])
        pgn_text = "\n\n".join(game["pgn"] for game in games if game.get("pgn"))
        if pgn_text:
            pgn_parts.append(pgn_text)
    return canonical_username, "\n\n".join(pgn_parts), len(archives)


def import_player_games(username):
    canonical_username, pgn_text, archive_count = fetch_player_pgn(username)
    result = import_pgn(pgn_text, canonical_username, provider="chesscom")
    result["username"] = canonical_username
    result["archive_count"] = archive_count
    return result
