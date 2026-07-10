import argparse

from chesscom import ChessComError, import_player_games as import_chesscom_games
from database import init_db, player_summary
from lichess import LichessError, import_player_games as import_lichess_games


IMPORTERS = {
    "chesscom": import_chesscom_games,
    "lichess": import_lichess_games,
}


def import_games(platform, username):
    result = IMPORTERS[platform](username)
    canonical_username = result["username"]
    summary = player_summary(canonical_username, provider=platform)

    print(f"\n[{platform}] {canonical_username}")
    print(f"새 게임: {result['added_games']}")
    print(f"중복 게임: {result['skipped_games']}")
    print(f"새 수: {result['added_moves']}")
    print(f"저장된 게임: {summary['games']}")
    print(f"저장된 내 수: {summary['player_moves']}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Chess.com 또는 Lichess 게임을 DB에 저장합니다."
    )
    parser.add_argument(
        "platform",
        choices=IMPORTERS,
        help="게임을 가져올 플랫폼",
    )
    parser.add_argument("username", help="플랫폼 사용자 아이디")
    return parser


if __name__ == "__main__":
    init_db()
    args = build_parser().parse_args()
    try:
        import_games(args.platform, args.username)
    except (ChessComError, LichessError) as exc:
        raise SystemExit(str(exc)) from exc
