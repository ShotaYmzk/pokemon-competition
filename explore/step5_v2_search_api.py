#!/usr/bin/env python3
"""STEP 5 v2: Search API - restore a real turn state and run one search cycle."""

import collections
import ctypes
import json
import random
import sys

from kaggle_environments.envs.cabt.cg.sim import lib, Battle
from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

print("=== STEP 5 v2: Search API (proper game state) ===\n")

random.seed(0)

with open("agent/deck.csv") as f:
    deck = [int(l.strip()) for l in f if l.strip()]
assert len(deck) == 60


IntPtr = ctypes.POINTER(ctypes.c_int)

lib.AgentStart.restype = ctypes.c_void_p
lib.AgentStart.argtypes = []

lib.SearchBegin.restype = ctypes.c_char_p
lib.SearchBegin.argtypes = [
    ctypes.c_void_p,  # agent_ptr
    ctypes.c_char_p,  # search_begin_input bytes
    ctypes.c_int,  # input length
    IntPtr,  # your_deck
    IntPtr,  # your_prize
    IntPtr,  # opponent_deck
    IntPtr,  # opponent_prize
    IntPtr,  # opponent_hand
    IntPtr,  # opponent_active / optional extra hidden list
    ctypes.c_int,  # manual_coin
]

# SearchStep also reads rsi/rdx/ecx:
#   const char* SearchStep(ApiData* agent, int search_id, int* action, int action_len)
lib.SearchStep.restype = ctypes.c_char_p
lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int, IntPtr, ctypes.c_int]

lib.SearchEnd.restype = None
lib.SearchEnd.argtypes = [ctypes.c_void_p]

if hasattr(lib, "SearchRelease"):
    lib.SearchRelease.restype = None
    lib.SearchRelease.argtypes = [ctypes.c_void_p]


def print_obs_summary(obs, label=""):
    sel = obs.get("select")
    cur = obs.get("current", {})
    sbi_len = len(obs.get("search_begin_input") or "")
    if sel:
        print(
            f"  [{label}] turn={cur.get('turn')} yourIndex={cur.get('yourIndex')} "
            f"select.type={sel.get('type')} context={sel.get('context')} "
            f"maxCount={sel.get('maxCount')} options={len(sel.get('option', []))} "
            f"sbi_len={sbi_len}"
        )
    else:
        print(f"  [{label}] select=None (deck selection phase) sbi_len={sbi_len}")


def card_ids(cards):
    ids = []
    for card in cards or []:
        if isinstance(card, dict):
            cid = card.get("id", card.get("cardId"))
            if isinstance(cid, int):
                ids.append(cid)
    return ids


def visible_card_ids(obs, player_index):
    player = obs["current"]["players"][player_index]
    ids = []
    for zone in ("hand", "active", "bench", "discard", "prize"):
        ids.extend(card_ids(player.get(zone)))
    return ids


def remaining_deck_guess(obs, player_index):
    """Deck order from observation is hidden; keep legal card IDs and remove visible cards."""
    remaining = collections.Counter(deck)
    for cid in visible_card_ids(obs, player_index):
        remaining[cid] -= 1

    guessed = []
    for cid in deck:
        if remaining[cid] > 0:
            guessed.append(cid)
            remaining[cid] -= 1
    return guessed


def make_int_array(values, min_len=64, filler=None):
    """Return a stable, non-NULL int array.

    SearchBegin has no length arguments for these six pointers. If the restored state
    needs N cards, C++ reads N ints from the pointer, so truly empty arrays or NULL can
    segfault. Padding uses valid card IDs so CopyIdPtr does not fail on filler.
    """
    vals = list(values)
    fill = list(filler or deck)
    while len(vals) < min_len:
        vals.append(fill[len(vals) % len(fill)])
    return (ctypes.c_int * len(vals))(*vals)


def summarize_hidden_inputs(name, arrays):
    sizes = ", ".join(f"{key}={len(vals)}" for key, vals in arrays.items())
    print(f"  candidate={name}: {sizes}")


def first_valid_search_action(select):
    if not select:
        return []
    option_count = len(select.get("option", []))
    min_count = select.get("minCount", 0)
    max_count = select.get("maxCount", 0)
    count = min(max(min_count, 1 if option_count else 0), max_count, option_count)
    return list(range(count))


def extract_search_id(begin_data):
    # Current libcg returns only {"state": ..., "error": 0}; the first search has id 0.
    state = begin_data.get("state")
    if isinstance(state, dict):
        for key in ("searchId", "searchId_", "searchIdH"):
            if isinstance(state.get(key), int):
                return state[key]
    for key in ("searchId", "searchId_", "searchIdH"):
        if isinstance(begin_data.get(key), int):
            return begin_data[key]
    return 0


def call_search_begin(agent_ptr, sbi_bytes, arrays):
    holders = [make_int_array(arrays[key]) for key in (
        "your_deck",
        "your_prize",
        "opp_deck",
        "opp_prize",
        "opp_hand",
        "opp_active",
    )]
    raw = lib.SearchBegin(agent_ptr, sbi_bytes, len(sbi_bytes), *holders, 0)
    text = raw.decode() if raw else ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"state": None, "error": "json"}
    return data, text


obs, start_data = battle_start(deck, deck)
if obs is None:
    print(f"[FAIL] battle_start failed: errorPlayer={start_data.errorPlayer} errorType={start_data.errorType}")
    sys.exit(1)

print(f"[OK] battle_start: battle_ptr={Battle.battle_ptr}")
print_obs_summary(obs, "start")

# Advance to a normal in-game decision. Use deterministic legal choices so results are reproducible.
MAX_SETUP_STEPS = 30
for step in range(MAX_SETUP_STEPS):
    cur = obs.get("current", {})
    sel = obs.get("select")

    if cur and cur.get("result", -1) >= 0:
        print(f"Game ended at setup step {step}: result={cur['result']}")
        battle_finish()
        sys.exit(1)

    if sel and cur.get("turn", 0) >= 1 and sel.get("type") in (0, 1, 2, 3, 4, 5, 6, 7):
        print(f"\n[OK] Reached main turn at setup step {step}")
        print_obs_summary(obs, "main_turn")
        break

    if sel is None:
        action = deck
    else:
        option_count = len(sel.get("option", []))
        action_count = min(sel.get("maxCount", 1), option_count)
        action = list(range(action_count))

    obs = battle_select(action)
    print_obs_summary(obs, f"step{step + 1}")
else:
    print("[WARN] Reached max setup steps, using current state anyway")

sbi = obs.get("search_begin_input") or ""
sbi_bytes = sbi.encode("ascii")
print(f"\nsearch_begin_input: {sbi[:80]!r}  (len={len(sbi_bytes)})")

your_index = obs["current"]["yourIndex"]
opp_index = 1 - your_index
your_player = obs["current"]["players"][your_index]
opp_player = obs["current"]["players"][opp_index]

your_visible = visible_card_ids(obs, your_index)
opp_visible = visible_card_ids(obs, opp_index)
your_deck_guess = remaining_deck_guess(obs, your_index)
opp_deck_guess = remaining_deck_guess(obs, opp_index)

print("\n--- Observed cards ---")
print(f"  your visible IDs ({len(your_visible)}): {your_visible}")
print(f"  opp visible IDs  ({len(opp_visible)}): {opp_visible}")
print(f"  your deckCount={your_player['deckCount']} guessed_remaining={len(your_deck_guess)}")
print(f"  opp  deckCount={opp_player['deckCount']} guessed_remaining={len(opp_deck_guess)}")

valid_empty = []
zero_filled = [0] * 64
full_deck = list(deck)

candidates = [
    (
        "observed_remaining",
        {
            "your_deck": your_deck_guess,
            "your_prize": valid_empty,
            "opp_deck": opp_deck_guess,
            "opp_prize": valid_empty,
            "opp_hand": card_ids(opp_player.get("hand")),
            "opp_active": card_ids(opp_player.get("active")),
        },
    ),
    (
        "full_deck_all_slots",
        {
            "your_deck": full_deck,
            "your_prize": full_deck,
            "opp_deck": full_deck,
            "opp_prize": full_deck,
            "opp_hand": full_deck,
            "opp_active": full_deck,
        },
    ),
    (
        "zero_filled_empty_arrays",
        {
            "your_deck": zero_filled,
            "your_prize": zero_filled,
            "opp_deck": zero_filled,
            "opp_prize": zero_filled,
            "opp_hand": zero_filled,
            "opp_active": zero_filled,
        },
    ),
]

print("\n--- SearchBegin trials ---")
agent_ptr = lib.AgentStart()
print(f"[OK] AgentStart: agent_ptr={agent_ptr}")

begin_data = None
begin_text = ""
winning_name = None

try:
    for name, arrays in candidates:
        summarize_hidden_inputs(name, arrays)
        begin_data, begin_text = call_search_begin(agent_ptr, sbi_bytes, arrays)
        print(f"    -> error={begin_data.get('error')} result={begin_text[:220]!r}")
        if begin_data.get("error") == 0:
            winning_name = name
            break

    if not winning_name:
        print("\n[FAIL] SearchBegin did not reach error=0")
        sys.exit(1)

    print(f"\n[OK] SearchBegin succeeded with candidate={winning_name}")

    search_id = extract_search_id(begin_data)
    step_action = first_valid_search_action(begin_data["state"]["observation"].get("select"))
    step_arr = make_int_array(step_action, min_len=max(1, len(step_action)))

    print("\n--- SearchStep ---")
    print(f"  args: search_id={search_id}, action={step_action}")
    step_raw = lib.SearchStep(agent_ptr, search_id, step_arr, len(step_action))
    step_text = step_raw.decode() if step_raw else ""
    print(f"  SearchStep result: {step_text[:500]!r}")
    step_data = json.loads(step_text) if step_text else {"error": "empty"}
    print(f"  error={step_data.get('error')}")

    print("\n--- SearchEnd ---")
    lib.SearchEnd(agent_ptr)
    print("[OK] SearchEnd called")

    print("\n*** STEP 5 RESULT: SearchBegin(error=0), SearchStep, SearchEnd completed ***")
finally:
    if agent_ptr and hasattr(lib, "SearchRelease"):
        lib.SearchRelease(agent_ptr)
    battle_finish()

print("\n=== STEP 5 v2 Complete ===")
