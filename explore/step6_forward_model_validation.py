#!/usr/bin/env python3
"""STEP 6: Forward-model validation for the cabt search API.

1. Random self-play (battle_start/battle_select) to a mid-game decision point.
2. Build a determinized SearchBegin state: own cards = real observed IDs,
   opponent's hidden cards sampled from deck.csv minus all visible cards.
3. For each legal action in select.option, call SearchStep and sanity-check the
   resulting state (legal moves, prize/side counts, terminal/winner detection).
4. Run a full random playout purely via SearchStep from that state to game end,
   read off winner/reward.

Findings are appended to findings.md under "## STEP 7" by this script's caller
(see explore/step7_greedy_and_writeup.py / manual edit) — this script focuses on
producing and printing the validation evidence.
"""

import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

try:
    from explore.search_api import (
        agent_start,
        card_ids,
        first_valid_search_action,
        search_begin,
        search_end,
        search_step,
        visible_card_ids,
    )
except ImportError:
    from search_api import (
        agent_start,
        card_ids,
        first_valid_search_action,
        search_begin,
        search_end,
        search_step,
        visible_card_ids,
    )


def sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng):
    """Build a LEGAL determinization of hidden information (Task B requirement).

    IMPORTANT (confirmed empirically): each player has their OWN independent
    60-card deck -- battle_start(deck, deck) gives both players a deck with the
    SAME composition, but they are two separate physical 60-card pools, not one
    shared 120-card pool split between players. So "unseen" must be computed
    PER PLAYER: your hidden cards (own prize) come from deck-minus-your-visible;
    the opponent's hidden cards (opp prize/hand/deck) come from a SEPARATE
    deck-minus-opp-visible pool. Mixing the two into a single 60-card multiset
    (an earlier, buggy version of this function) produces an impossible
    requirement, e.g. needing 63 cards from a 49-card pool, because it
    double-subtracts each side's own visible cards against the other side's
    budget.

    Each side's hidden cards are sampled WITHOUT REPLACEMENT (collections.Counter
    multiset subtraction + random.sample) from that side's own 60-card deck
    composition minus the cards already visible for that side. This respects
    deck legality, unlike the step5_v2 placeholder tricks (full_deck_all_slots/
    zero_filled) and unlike a plain "remaining in deck order" guess
    (remaining_deck_guess), which does not randomize.
    """
    your_player = obs["current"]["players"][your_index]
    opp_player = obs["current"]["players"][opp_index]

    your_visible = visible_card_ids(obs, your_index)
    opp_visible = visible_card_ids(obs, opp_index)

    # --- your side: only your prize identities are hidden (from yourself) ---
    your_unseen = collections.Counter(deck)
    for cid in your_visible:
        your_unseen[cid] -= 1
    your_unseen_pool = []
    for cid, n in your_unseen.items():
        if n > 0:
            your_unseen_pool.extend([cid] * n)

    your_prize_count = len(your_player["prize"])
    if your_prize_count > len(your_unseen_pool):
        raise ValueError(
            f"Need {your_prize_count} unseen cards for your_prize but your pool only has "
            f"{len(your_unseen_pool)}. pool={collections.Counter(your_unseen_pool)}"
        )
    your_prize_sample = rng.sample(your_unseen_pool, your_prize_count)

    # remaining of your own deck = your_unseen_pool minus the sampled prize cards,
    # capped at deckCount (the rest, if any slack, is impossible by construction
    # since your_visible + prize + deckCount should equal exactly 60).
    your_deck_visible_removed = collections.Counter(your_unseen_pool)
    for cid in your_prize_sample:
        your_deck_visible_removed[cid] -= 1
    your_deck_sample = []
    for cid in deck:
        if your_deck_visible_removed[cid] > 0:
            your_deck_sample.append(cid)
            your_deck_visible_removed[cid] -= 1
    your_deck_sample = your_deck_sample[: your_player["deckCount"]]

    # --- opponent side: prize + hand + deck are all hidden from you ---
    opp_unseen = collections.Counter(deck)
    for cid in opp_visible:
        opp_unseen[cid] -= 1
    opp_unseen_pool = []
    for cid, n in opp_unseen.items():
        if n > 0:
            opp_unseen_pool.extend([cid] * n)

    opp_prize_count = len(opp_player["prize"])
    opp_hand_count = opp_player["handCount"]
    opp_deck_count = opp_player["deckCount"]
    needed = opp_prize_count + opp_hand_count + opp_deck_count
    if needed > len(opp_unseen_pool):
        raise ValueError(
            f"Need {needed} unseen cards (opp_prize={opp_prize_count} "
            f"opp_hand={opp_hand_count} opp_deck={opp_deck_count}) but opp pool only has "
            f"{len(opp_unseen_pool)}. pool={collections.Counter(opp_unseen_pool)}"
        )

    sampled = rng.sample(opp_unseen_pool, needed)
    opp_prize_sample = sampled[:opp_prize_count]
    opp_hand_sample = sampled[opp_prize_count: opp_prize_count + opp_hand_count]
    opp_deck_sample = sampled[opp_prize_count + opp_hand_count:]

    return {
        "your_deck": your_deck_sample,
        "your_prize": your_prize_sample,
        "opp_deck": opp_deck_sample,
        "opp_prize": opp_prize_sample,
        "opp_hand": opp_hand_sample,
        "opp_active": card_ids(opp_player.get("active")),
    }


def load_deck():
    with open(os.path.join(os.path.dirname(__file__), "..", "agent", "deck.csv")) as f:
        deck = [int(l.strip()) for l in f if l.strip()]
    assert len(deck) == 60
    return deck


def advance_to_midgame(deck, seed, min_turn=2, max_steps=200):
    """Random self-play via battle_start/battle_select to a mid-game decision point."""
    random.seed(seed)
    obs, start_data = battle_start(deck, deck)
    if obs is None:
        raise RuntimeError(f"battle_start failed: {start_data}")

    for step in range(max_steps):
        cur = obs.get("current", {})
        if cur and cur.get("result", -1) >= 0:
            raise RuntimeError(f"game ended during setup at step {step}, result={cur['result']}")

        sel = obs.get("select")
        if sel and cur.get("turn", 0) >= min_turn and sel.get("option"):
            return obs, step

        if sel is None:
            action = deck
        else:
            opts = sel.get("option", [])
            mc = min(sel.get("maxCount", 1), len(opts))
            action = random.sample(range(len(opts)), mc) if opts else []
        obs = battle_select(action)

    raise RuntimeError("did not reach mid-game within max_steps")


def prize_counts(state_obs, your_index):
    """**Field path for reading side/prize counts from a SearchState observation:**
    state['observation']['current']['players'][i]['prize'] is a list (len = prizes
    remaining unclaimed for that side at battle start: 6); entries are `null` while
    face-down and become card dicts once revealed/taken. The remaining prize COUNT
    for side i is len(players[i]['prize']) (shrinks as prizes are taken).
    """
    cur = state_obs["current"]
    return [len(p["prize"]) for p in cur["players"]]


def terminal_info(state_obs):
    """**Field path for terminal/winner detection:**
    state['observation']['current']['result'] is -1 while the game is ongoing.
    Once finished it becomes the winning playerIndex (0 or 1), or 2 for a draw,
    matching cg/game.py's battle_finish semantics. select becomes None/absent-ish
    (select.option empty) once the game is terminal in the search chain too.
    """
    cur = state_obs["current"]
    return cur.get("result", -1)


def main():
    deck = load_deck()
    log = []

    def record(msg):
        print(msg)
        log.append(msg)

    record("=== STEP 6: Forward Model Validation ===\n")

    # ---- 1. Random self-play to mid-game ----
    obs, setup_steps = advance_to_midgame(deck, seed=7, min_turn=2)
    cur = obs["current"]
    your_index = cur["yourIndex"]
    opp_index = 1 - your_index
    record(f"[1] Reached mid-game at real-play step {setup_steps}, turn={cur['turn']}, yourIndex={your_index}")

    your_player = cur["players"][your_index]
    opp_player = cur["players"][opp_index]
    record(f"    my prize remaining={len(your_player['prize'])} opp prize remaining={len(opp_player['prize'])}")
    record(f"    my active={your_player['active']}")
    record(f"    opp active={opp_player['active']}")

    # ---- 2. Determinized SearchBegin state (proper random sampling, not a placeholder) ----
    sbi_bytes = (obs.get("search_begin_input") or "").encode("ascii")
    rng = random.Random(7)
    try:
        arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng)
    except ValueError as e:
        record(f"\n[2] [FAIL] determinization failed: {e}")
        battle_finish()
        write_findings(log)
        return
    record(
        f"\n[2] Determinization (random.sample w/o replacement over unseen multiset): "
        f"your_deck_sample len={len(arrays['your_deck'])} opp_deck_sample len={len(arrays['opp_deck'])} "
        f"opp_hand_sample len={len(arrays['opp_hand'])}"
    )
    record("    (deck.csv 60-card multiset minus ALL visible cards -- including preEvolution -- on both sides)")
    record(f"    my deckCount={your_player['deckCount']} opp deckCount={opp_player['deckCount']}")

    agent_ptr = agent_start()
    begin_data, begin_text = search_begin(
        agent_ptr, sbi_bytes,
        your_deck=arrays["your_deck"], your_prize=arrays["your_prize"],
        opp_deck=arrays["opp_deck"], opp_prize=arrays["opp_prize"],
        opp_hand=arrays["opp_hand"],
        opp_active=arrays["opp_active"],
        deck_filler=deck,
    )
    record(f"\n    SearchBegin error={begin_data.get('error')}")
    if begin_data.get("error") != 0:
        record(f"    [FAIL] SearchBegin did not return error=0: {begin_text[:500]}")
        search_end(agent_ptr)
        battle_finish()
        write_findings(log)
        return

    state0 = begin_data["state"]
    sel0 = state0["observation"].get("select")
    record(f"    select.option count={len(sel0.get('option', []))} type={sel0.get('type')}")

    # ---- 3. For each legal action, SearchStep + sanity checks ----
    record("\n[3] Per-action SearchStep sanity checks:")
    options = sel0.get("option", [])
    min_count = sel0.get("minCount", 0)
    max_count = sel0.get("maxCount", 1)

    checked = 0
    for idx in range(len(options)):
        if checked >= 8:
            break  # bound exploration; enough for validation evidence
        count = max(min_count, 1)
        count = min(count, max_count, 1)
        action = [idx] if count == 1 else list(range(min(count, len(options))))

        step_data, step_text = search_step(agent_ptr, 0, action)
        err = step_data.get("error")
        ok_state = step_data.get("state") is not None
        next_sel = None
        prizes = None
        result = None
        if ok_state:
            next_obs = step_data["state"]["observation"]
            next_sel = next_obs.get("select")
            prizes = prize_counts(next_obs, your_index)
            result = terminal_info(next_obs)
        record(
            f"    action_idx={idx} option={options[idx]} -> error={err} "
            f"next_select_options={len(next_sel.get('option', [])) if next_sel else None} "
            f"prizes(mine,opp)={prizes} result={result}"
        )
        checked += 1

    # ---- 4. Full random playout purely via SearchStep ----
    record("\n[4] Full random playout via repeated SearchStep from this state:")
    cur_state = state0
    n_search_steps = 0
    max_search_steps = 2000
    final_result = None
    error_hit = None

    while n_search_steps < max_search_steps:
        obs_s = cur_state["observation"]
        result = terminal_info(obs_s)
        if result is not None and result >= 0:
            final_result = result
            break
        sel = obs_s.get("select")
        if not sel or not sel.get("option"):
            record(f"    [WARN] no legal options at step {n_search_steps}, treating as terminal (result field={result})")
            final_result = result
            break

        opts = sel.get("option", [])
        mc = min(sel.get("maxCount", 1), len(opts))
        mc = max(mc, sel.get("minCount", 0))
        mc = min(mc, len(opts))
        action = random.sample(range(len(opts)), mc) if mc > 0 else []

        step_data, step_text = search_step(agent_ptr, 0, action)
        n_search_steps += 1
        if step_data.get("error") != 0:
            error_hit = (n_search_steps, step_data.get("error"), step_text[:500])
            record(f"    [ERROR] SearchStep failed at step {n_search_steps}: error={step_data.get('error')} text={step_text[:300]!r}")
            break
        cur_state = step_data["state"]

    if error_hit:
        record(f"    Playout stopped early due to error: {error_hit}")
    else:
        record(f"    Playout completed in {n_search_steps} SearchStep calls, final result={final_result}")
        prizes_final = prize_counts(cur_state["observation"], your_index)
        record(f"    Final prize counts (mine, opp)={prizes_final}")
        if final_result == your_index:
            record(f"    Winner: ME (player {your_index})")
        elif final_result == opp_index:
            record(f"    Winner: OPPONENT (player {opp_index})")
        elif final_result == 2:
            record("    Result: DRAW")
        else:
            record(f"    Result: unrecognized terminal value {final_result}")

    search_end(agent_ptr)
    battle_finish()

    record("\n=== STEP 6 Complete ===")
    write_findings(log)
    return log


def write_findings(log):
    out_path = os.path.join(os.path.dirname(__file__), "step6_output.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(log))
    print(f"\n[saved raw log to {out_path}]")


if __name__ == "__main__":
    main()
