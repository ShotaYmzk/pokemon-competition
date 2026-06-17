#!/usr/bin/env python3
"""Reusable ctypes wiring for the cabt search API (SearchBegin/SearchStep/SearchEnd).

Extracted from explore/step5_v2_search_api.py. No top-level side effects: importing
this module does not start a battle or call into libcg beyond setting up ctypes
argtypes/restypes (which is required once per process before the calls are usable).

Usage:
    from explore.search_api import agent_start, search_begin, search_step, search_end

    agent_ptr = agent_start()
    state, err = search_begin(agent_ptr, sbi_bytes, your_deck, your_prize,
                               opp_deck, opp_prize, opp_hand, opp_active)
    state2, err2 = search_step(agent_ptr, 0, [0])
    search_end(agent_ptr)
"""

import collections
import ctypes
import json

from kaggle_environments.envs.cabt.cg.sim import lib

IntPtr = ctypes.POINTER(ctypes.c_int)

_TYPES_BOUND = False


def _bind_types():
    """Set ctypes argtypes/restypes on the shared `lib` handle. Idempotent."""
    global _TYPES_BOUND
    if _TYPES_BOUND:
        return

    lib.AgentStart.restype = ctypes.c_void_p
    lib.AgentStart.argtypes = []

    lib.SearchBegin.restype = ctypes.c_char_p
    lib.SearchBegin.argtypes = [
        ctypes.c_void_p,  # agent_ptr (must be AgentStart() result, NOT battle_ptr)
        ctypes.c_char_p,  # search_begin_input bytes
        ctypes.c_int,  # input length
        IntPtr,  # your_deck
        IntPtr,  # your_prize
        IntPtr,  # opponent_deck
        IntPtr,  # opponent_prize
        IntPtr,  # opponent_hand
        IntPtr,  # opponent_active
        ctypes.c_int,  # manual_coin
    ]

    lib.SearchStep.restype = ctypes.c_char_p
    lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int, IntPtr, ctypes.c_int]

    lib.SearchEnd.restype = None
    lib.SearchEnd.argtypes = [ctypes.c_void_p]

    if hasattr(lib, "SearchRelease"):
        lib.SearchRelease.restype = None
        lib.SearchRelease.argtypes = [ctypes.c_void_p]

    _TYPES_BOUND = True


def agent_start():
    """Create a search-only agent pointer (AgentStart, type field = 2).

    This is distinct from the battle_ptr created by battle_start() (type field = 1).
    Passing battle_ptr into SearchBegin produces error=30.
    """
    _bind_types()
    return lib.AgentStart()


def make_int_array(values, min_len=64, filler=None, deck=None):
    """Build a stable, non-NULL ctypes int array.

    SearchBegin has no separate length arguments for its six int* pointers, so the
    C++ side reads as many ints as the restored state needs. Truly empty/NULL arrays
    can segfault or behave inconsistently. We pad with valid card IDs (from `filler`
    or `deck`) so padding never represents an invalid card.
    """
    vals = list(values)
    fill = list(filler or deck or [1])
    while len(vals) < min_len:
        vals.append(fill[len(vals) % len(fill)])
    return (ctypes.c_int * len(vals))(*vals)


def card_ids(cards):
    """Extract integer card IDs from a list of card dicts (handles 'id' or 'cardId')."""
    ids = []
    for card in cards or []:
        if isinstance(card, dict):
            cid = card.get("id", card.get("cardId"))
            if isinstance(cid, int):
                ids.append(cid)
    return ids


def visible_card_ids(obs, player_index):
    """All card IDs currently visible (hand/active/bench/discard/prize) for a player."""
    player = obs["current"]["players"][player_index]
    ids = []
    for zone in ("hand", "active", "bench", "discard", "prize"):
        ids.extend(card_ids(player.get(zone)))
    return ids


def remaining_deck_guess(obs, player_index, deck):
    """Guess the cards remaining in a player's deck: full deck list minus visible cards.

    `deck` is the known 60-card decklist (deck.csv contents) used by both players in
    this harness. The true deck order/identity beyond visible cards is hidden info;
    this produces one consistent (not necessarily exact) determinization.
    """
    remaining = collections.Counter(deck)
    for cid in visible_card_ids(obs, player_index):
        remaining[cid] -= 1

    guessed = []
    for cid in deck:
        if remaining[cid] > 0:
            guessed.append(cid)
            remaining[cid] -= 1
    return guessed


def _parse(raw):
    text = raw.decode() if raw else ""
    try:
        data = json.loads(text) if text else {"error": "empty"}
    except json.JSONDecodeError:
        data = {"state": None, "error": "json"}
    return data, text


def search_begin(agent_ptr, sbi_bytes, your_deck, your_prize, opp_deck, opp_prize,
                  opp_hand, opp_active, manual_coin=0, deck_filler=None):
    """Call SearchBegin and return (parsed_json_dict, raw_text).

    All of your_deck/your_prize/opp_deck/opp_prize/opp_hand/opp_active are plain
    python lists of card IDs; they get padded to a safe minimum length internally.
    """
    _bind_types()
    arrays = [your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active]
    holders = [make_int_array(a, filler=deck_filler) for a in arrays]
    raw = lib.SearchBegin(agent_ptr, sbi_bytes, len(sbi_bytes), *holders, manual_coin)
    return _parse(raw)


def search_step(agent_ptr, search_id, action):
    """Call SearchStep(agent_ptr, search_id, action_list) and return (parsed, raw_text)."""
    _bind_types()
    action = list(action)
    arr = make_int_array(action, min_len=max(1, len(action)), filler=action or [0])
    raw = lib.SearchStep(agent_ptr, search_id, arr, len(action))
    return _parse(raw)


def search_end(agent_ptr):
    """Call SearchEnd to release the search chain (and SearchRelease if available)."""
    _bind_types()
    lib.SearchEnd(agent_ptr)
    if hasattr(lib, "SearchRelease"):
        lib.SearchRelease(agent_ptr)


def first_valid_search_action(select):
    """Pick a deterministic, legal action (list of option indices) for a select dict."""
    if not select:
        return []
    option_count = len(select.get("option", []))
    min_count = select.get("minCount", 0)
    max_count = select.get("maxCount", 0)
    count = min(max(min_count, 1 if option_count else 0), max_count, option_count)
    return list(range(count))


if __name__ == "__main__":
    # Smoke test: one begin/step/end cycle using a real mid-game state.
    import sys
    import random

    from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

    random.seed(0)
    with open("agent/deck.csv") as f:
        deck = [int(l.strip()) for l in f if l.strip()]
    assert len(deck) == 60

    obs, start_data = battle_start(deck, deck)
    if obs is None:
        print(f"[FAIL] battle_start: {start_data}")
        sys.exit(1)

    for step in range(30):
        cur = obs.get("current", {})
        sel = obs.get("select")
        if cur and cur.get("result", -1) >= 0:
            print("[FAIL] game ended during setup")
            battle_finish()
            sys.exit(1)
        if sel and cur.get("turn", 0) >= 1:
            break
        if sel is None:
            action = deck
        else:
            oc = len(sel.get("option", []))
            mc = min(sel.get("maxCount", 1), oc)
            action = list(range(mc))
        obs = battle_select(action)

    sbi_bytes = (obs.get("search_begin_input") or "").encode("ascii")
    your_index = obs["current"]["yourIndex"]
    opp_index = 1 - your_index
    opp_player = obs["current"]["players"][opp_index]

    your_guess = remaining_deck_guess(obs, your_index, deck)
    opp_guess = remaining_deck_guess(obs, opp_index, deck)

    try:
        agent_ptr = agent_start()
        print(f"[OK] agent_start -> {agent_ptr}")

        begin_data, begin_text = search_begin(
            agent_ptr, sbi_bytes,
            your_deck=your_guess, your_prize=[],
            opp_deck=opp_guess, opp_prize=[],
            opp_hand=card_ids(opp_player.get("hand")),
            opp_active=card_ids(opp_player.get("active")),
            deck_filler=deck,
        )
        print(f"[OK] search_begin error={begin_data.get('error')}")
        assert begin_data.get("error") == 0, begin_text

        action = first_valid_search_action(begin_data["state"]["observation"].get("select"))
        step_data, step_text = search_step(agent_ptr, 0, action)
        print(f"[OK] search_step error={step_data.get('error')}")
        assert step_data.get("error") == 0, step_text

        search_end(agent_ptr)
        print("[OK] search_end called")
        print("\n*** search_api.py smoke test passed (error=0 throughout) ***")
    finally:
        battle_finish()
