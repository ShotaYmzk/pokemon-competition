#!/usr/bin/env python3
"""STEP 6b: 100-seed sweep validating the multi-select SearchStep fix.

For each seed: random self-play (battle_start/battle_select) to a mid-game decision
point, determinize hidden info, SearchBegin, then run a full random playout purely
via SearchStep (using the fixed search_step() wrapper in explore/search_api.py,
which now submits multi-select picks one index at a time -- see findings.md
"Multi-select SearchStep action encoding").

Reports: how many of the 100 seeds complete with ZERO error=4/5 (or any nonzero
error) during the playout, vs how many still hit an error, with the exact
error code and the select context that caused it for any failures.

This intentionally does NOT require reaching result != -1 within a step budget --
games can run long under pure random play -- the requirement is purely "no
SearchStep error" for as many steps as we run (capped at max_search_steps).
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

from explore.search_api import agent_start, search_begin, search_end, search_step
from explore.step6_forward_model_validation import (
    load_deck,
    advance_to_midgame,
    sample_determinized_hidden_state,
    prize_counts,
    terminal_info,
)

MAX_SEARCH_STEPS = 500
N_SEEDS = 300


def run_one_seed(deck, seed):
    """Returns a dict describing the outcome for this seed."""
    try:
        obs, setup_steps = advance_to_midgame(deck, seed=seed, min_turn=2)
    except Exception as e:
        return {"seed": seed, "status": "setup_failed", "detail": str(e)}

    cur = obs["current"]
    your_index = cur["yourIndex"]
    opp_index = 1 - your_index
    sbi_bytes = (obs.get("search_begin_input") or "").encode("ascii")
    rng = random.Random(seed)

    try:
        arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng)
    except (ValueError, AssertionError) as e:
        battle_finish()
        return {"seed": seed, "status": "determinize_failed", "detail": str(e)}

    agent_ptr = agent_start()
    begin_data, begin_text = search_begin(
        agent_ptr, sbi_bytes,
        your_deck=arrays["your_deck"], your_prize=arrays["your_prize"],
        opp_deck=arrays["opp_deck"], opp_prize=arrays["opp_prize"],
        opp_hand=arrays["opp_hand"], opp_active=arrays["opp_active"],
        deck_filler=deck,
    )
    if begin_data.get("error") != 0:
        search_end(agent_ptr)
        battle_finish()
        return {"seed": seed, "status": "search_begin_failed", "detail": begin_text[:300]}

    cur_state = begin_data["state"]
    n_steps = 0
    multi_select_calls = 0
    result = None
    error_info = None

    while n_steps < MAX_SEARCH_STEPS:
        obs_s = cur_state["observation"]
        res = terminal_info(obs_s)
        if res is not None and res >= 0:
            result = res
            break
        sel = obs_s.get("select")
        if not sel or not sel.get("option"):
            result = res
            break

        opts = sel.get("option", [])
        mc = min(sel.get("maxCount", 1), len(opts))
        mc = max(mc, sel.get("minCount", 0))
        mc = min(mc, len(opts))
        action = random.sample(range(len(opts)), mc) if mc > 0 else []
        if mc > 1:
            multi_select_calls += 1

        step_data, step_text = search_step(agent_ptr, 0, action, select=sel)
        n_steps += 1
        if step_data.get("error") != 0:
            error_info = {
                "step": n_steps,
                "error": step_data.get("error"),
                "raw": step_text[:300],
                "select_context": sel.get("context"),
                "select_type": sel.get("type"),
                "minCount": sel.get("minCount"),
                "maxCount": sel.get("maxCount"),
                "action": action,
            }
            break
        cur_state = step_data["state"]

    search_end(agent_ptr)
    battle_finish()

    if error_info is not None:
        return {"seed": seed, "status": "error", "n_steps": n_steps,
                "multi_select_calls": multi_select_calls, "error_info": error_info}
    if result is not None and result >= 0:
        return {"seed": seed, "status": "terminal", "n_steps": n_steps,
                "multi_select_calls": multi_select_calls, "result": result}
    return {"seed": seed, "status": "step_cap_reached_no_error", "n_steps": n_steps,
            "multi_select_calls": multi_select_calls}


def main():
    deck = load_deck()
    outcomes = []
    for seed in range(N_SEEDS):
        outcomes.append(run_one_seed(deck, seed))

    n_clean = sum(1 for o in outcomes if o["status"] in ("terminal", "step_cap_reached_no_error"))
    n_error = sum(1 for o in outcomes if o["status"] == "error")
    n_setup_failed = sum(1 for o in outcomes if o["status"] in ("setup_failed", "determinize_failed", "search_begin_failed"))
    n_terminal = sum(1 for o in outcomes if o["status"] == "terminal")
    n_multi_select_seen = sum(1 for o in outcomes if o.get("multi_select_calls", 0) > 0)

    print("=== STEP 6b: 100-seed SearchStep multi-select fix validation ===\n")
    print(f"Total seeds run: {N_SEEDS}")
    print(f"  Clean (no SearchStep error -- either reached terminal or hit step cap cleanly): {n_clean}")
    print(f"    of which reached an actual terminal result (result != -1): {n_terminal}")
    print(f"  SearchStep error encountered (error=4/5/other): {n_error}")
    print(f"  Setup/determinize/search_begin failures (unrelated to SearchStep action encoding): {n_setup_failed}")
    print(f"  Seeds whose playout encountered at least one multi-select (minCount/maxCount>1) decision: {n_multi_select_seen}")
    print()
    print(f"PASS RATE (no SearchStep error / total): {n_clean}/{N_SEEDS} = {100.0 * n_clean / N_SEEDS:.1f}%")
    print()

    if n_error:
        print("Details of seeds that still errored:")
        for o in outcomes:
            if o["status"] == "error":
                print(f"  seed={o['seed']} step={o['n_steps']} multi_select_calls_seen={o['multi_select_calls']} "
                      f"error_info={o['error_info']}")

    if n_setup_failed:
        print("\nSetup/determinize failures (pre-existing, unrelated to this fix):")
        for o in outcomes:
            if o["status"] in ("setup_failed", "determinize_failed", "search_begin_failed"):
                print(f"  seed={o['seed']} status={o['status']} detail={o.get('detail')}")

    return outcomes


if __name__ == "__main__":
    main()
