import requests
from datetime import datetime, timezone

from database import import_pgn, latest_game_date


API_ROOT = "https://lichess.org/api"
HEADERS = {
    "Accept": "application/x-chess-pgn",
    "User-Agent": "ChessAnalysisProject/1.0 (local chess analysis app)",
}


class LichessError(RuntimeError):
    pass


def get_profile(username):
    try:
        response = requests.get(
            f"{API_ROOT}/user/{username}",
            headers={"Accept": "application/json", "User-Agent": HEADERS["User-Agent"]},
            timeout=25,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise LichessError(f"Lichess 사용자 조회에 실패했습니다: {exc}") from exc


def fetch_player_pgn(username, since_date=None):
    profile = get_profile(username)
    canonical_username = profile.get("username") or username

    params = {
        "clocks": "false",
        "evals": "false",
        "opening": "false",
        "literate": "false",
        "pgnInJson": "false",
    }
    if since_date:
        try:
            since = datetime.fromisoformat(since_date).replace(tzinfo=timezone.utc)
            params["since"] = int(since.timestamp() * 1000)
        except ValueError:
            pass

    try:
        response = requests.get(
            f"{API_ROOT}/games/user/{canonical_username}",
            headers=HEADERS,
            params=params,
            timeout=180,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LichessError(f"Lichess 게임 요청에 실패했습니다: {exc}") from exc

    return canonical_username, response.text


def import_player_games(username):
    since_date = latest_game_date(username, "lichess")
    canonical_username, pgn_text = fetch_player_pgn(username, since_date=since_date)
    result = import_pgn(pgn_text, canonical_username, provider="lichess")
    result["username"] = canonical_username
    return result
