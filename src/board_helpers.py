import json

import chess


TIME_CLASS_LABELS = {
    "bullet": "불렛",
    "blitz": "블리츠",
    "rapid": "래피드",
    "daily": "일일",
    "unknown": "기타",
}


def fen_lookup_keys(fen):
    parts = fen.split(" ")
    if len(parts) < 4:
        return [fen]
    exact_key = " ".join(parts[:4])
    no_ep_key = " ".join(parts[:3] + ["-"])
    return list(dict.fromkeys([exact_key, no_ep_key]))


def parse_time_classes(value):
    allowed = {"bullet", "blitz", "rapid", "daily", "unknown"}
    classes = [
        item.strip().lower()
        for item in (value or "").split(",")
        if item.strip().lower() in allowed
    ]
    return list(dict.fromkeys(classes))


def player_result(result, player_color):
    if result == "1/2-1/2":
        return "무"
    if result not in {"1-0", "0-1"}:
        return result or "-"
    if player_color == "white":
        return "승" if result == "1-0" else "패"
    if player_color == "black":
        return "승" if result == "0-1" else "패"
    return result


def opponent_for_game(row):
    color = (row["player_color"] or "").lower()
    if color == "white":
        return row["black"] or "-"
    if color == "black":
        return row["white"] or "-"
    return f"{row['white'] or '?'} / {row['black'] or '?'}"


def san_for_uci(fen, uci):
    if not uci:
        return None
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            return uci
        return board.san(move)
    except ValueError:
        return uci


def san_line(fen, line_json):
    if not fen:
        return []
    try:
        line = json.loads(line_json or "[]")
    except (TypeError, ValueError):
        line = []
    board = chess.Board(fen)
    result = []
    for uci in line:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        result.append(board.san(move))
        board.push(move)
    return result
