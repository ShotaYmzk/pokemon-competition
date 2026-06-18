#!/usr/bin/env python3
"""Diagnostic: dump the exact select dict and action that triggers error=4/5 in
the SearchStep-driven playout from step6, then separately replay the SAME RNG
seed through battle_start/battle_select (ground truth) to see what select dicts
look like at the analogous multi-select decision and what battle_select accepts.
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

from explore.search_api import (
    agent_start, card_ids, search_begin, search_end, search_step, visible_card_ids,
)
from explore.step6_forward_model_validation import (
    load_deck, advance_to_midgame, sample_determinized_hidden_state, prize_counts, terminal_info,
)


def main():
    deck = load_deck()
    obs, setup_steps = advance_to_midgame(deck, seed=7, min_turn=2)
    cur = obs["current"]
    your_index = cur["yourIndex"]
    opp_index = 1 - your_index

    sbi_bytes = (obs.get("search_begin_input") or "").encode("ascii")
    rng = random.Random(7)
    arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng)

    agent_ptr = agent_start()
    begin_data, begin_text = search_begin(
        agent_ptr, sbi_bytes,
        your_deck=arrays["your_deck"], your_prize=arrays["your_prize"],
        opp_deck=arrays["opp_deck"], opp_prize=arrays["opp_prize"],
        opp_hand=arrays["opp_hand"], opp_active=arrays["opp_active"],
        deck_filler=deck,
    )
    assert begin_data.get("error") == 0, begin_text

    state0 = begin_data["state"]
    cur_state = state0
    n = 0
    history = []
    while n < 2000:
        obs_s = cur_state["observation"]
        result = terminal_info(obs_s)
        if result is not None and result >= 0:
            print(f"Reached terminal result={result} after {n} steps without error.")
            break
        sel = obs_s.get("select")
        if not sel or not sel.get("option"):
            print(f"No legal options at step {n}; stopping.")
            break
        opts = sel.get("option", [])
        mc = min(sel.get("maxCount", 1), len(opts))
        mc = max(mc, sel.get("minCount", 0))
        mc = min(mc, len(opts))
        action = random.sample(range(len(opts)), mc) if mc > 0 else []
        history.append({"step": n, "select": sel, "action": action})

        step_data, step_text = search_step(agent_ptr, 0, action)
        n += 1
        if step_data.get("error") != 0:
            print(f"\n=== ERROR at SearchStep call #{n} ===")
            print("error:", step_data.get("error"))
            print("raw text:", step_text)
            print("select type:", sel.get("type"), "context:", sel.get("context"),
                  "minCount:", sel.get("minCount"), "maxCount:", sel.get("maxCount"),
                  "n_options:", len(opts), "effect:", sel.get("effect"))
            print("action sent:", action)
            print("deck field len (if present):", len(sel.get("deck") or []))
            print("options:", json.dumps(opts, default=str))
            break
        cur_state = step_data["state"]

    search_end(agent_ptr)
    battle_finish()

    print("\n\n=== History of select/action pairs leading up to the error (last 6) ===")
    for h in history[-6:]:
        print(f"step={h['step']} action={h['action']} select_type={h['select'].get('type')} "
              f"minCount={h['select'].get('minCount')} maxCount={h['select'].get('maxCount')} "
              f"n_options={len(h['select'].get('option', []))}")


if __name__ == "__main__":
    main()
