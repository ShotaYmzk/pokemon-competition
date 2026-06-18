"""Feature extraction for cabt observations."""


def _player_state(state, player):
    current = state.get("current", state)
    players = current.get("players") or []
    if player < 0 or player >= len(players):
        return current, {}, {}
    return current, players[player] or {}, players[1 - player] or {}


def _zone_count(player_state, zone, count_key=None):
    cards = player_state.get(zone)
    if isinstance(cards, list):
        return len(cards)
    if count_key is not None:
        value = player_state.get(count_key)
        if isinstance(value, int):
            return value
    return 0


def _active_hp_ratio(player_state):
    active = player_state.get("active") or []
    card = active[0] if active and isinstance(active[0], dict) else None
    if not card:
        return 1.0

    hp = card.get("hp")
    max_hp = card.get("maxHp") or card.get("maxHP") or card.get("baseHp") or card.get("printedHp")
    if not isinstance(hp, (int, float)):
        return 1.0
    if not isinstance(max_hp, (int, float)) or max_hp <= 0:
        max_hp = hp
    if max_hp <= 0:
        return 1.0
    return max(0.0, min(1.0, float(hp) / float(max_hp)))


def extract_features(state, player):
    current, me, opp = _player_state(state, player)
    my_prize = _zone_count(me, "prize")
    opp_prize = _zone_count(opp, "prize")

    return {
        "prize_diff": my_prize - opp_prize,
        "my_prize": my_prize,
        "opp_prize": opp_prize,
        "my_active_hp_ratio": _active_hp_ratio(me),
        "opp_active_hp_ratio": _active_hp_ratio(opp),
        "my_bench_count": _zone_count(me, "bench"),
        "opp_bench_count": _zone_count(opp, "bench"),
        "my_hand_count": _zone_count(me, "hand", "handCount"),
        "opp_hand_count": _zone_count(opp, "hand", "handCount"),
        "turn": current.get("turn", 0),
    }
