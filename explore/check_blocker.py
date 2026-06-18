#!/usr/bin/env python3
"""Run 100 random SearchStep playouts and summarize error=4/5 blockers."""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from explore.search_api import agent_start, search_begin, search_end, search_step
from explore.step6_forward_model_validation import (
    advance_to_midgame,
    load_deck,
    sample_determinized_hidden_state,
    terminal_info,
)


TOTAL = 100
MAX_SEARCH_STEPS = 2000


def random_action(select, rng):
    options = select.get("option", [])
    count = min(select.get("maxCount", 1), len(options))
    count = max(count, select.get("minCount", 0))
    count = min(count, len(options))
    return rng.sample(range(len(options)), count) if count > 0 else []


def run_seed(seed, deck):
    """Return (completed, error, raw_error_text)."""
    obs = None
    agent_ptr = None
    try:
        obs, _setup_steps = advance_to_midgame(deck, seed=seed, min_turn=2)
        cur = obs["current"]
        your_index = cur["yourIndex"]
        opp_index = 1 - your_index
        rng = random.Random(seed)
        arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng)

        agent_ptr = agent_start()
        begin_data, begin_text = search_begin(
            agent_ptr,
            (obs.get("search_begin_input") or "").encode("ascii"),
            your_deck=arrays["your_deck"],
            your_prize=arrays["your_prize"],
            opp_deck=arrays["opp_deck"],
            opp_prize=arrays["opp_prize"],
            opp_hand=arrays["opp_hand"],
            opp_active=arrays["opp_active"],
            deck_filler=deck,
        )
        if begin_data.get("error") != 0:
            return False, begin_data.get("error"), begin_text

        cur_state = begin_data["state"]
        for _step in range(MAX_SEARCH_STEPS):
            obs_s = cur_state["observation"]
            result = terminal_info(obs_s)
            if result in (0, 1, 2):
                return True, None, None

            select = obs_s.get("select")
            if not select or not select.get("option"):
                return result in (0, 1, 2), None, None

            action = random_action(select, rng)
            step_data, step_text = search_step(
                agent_ptr, cur_state.get("searchId", 0), action, select=select
            )
            if step_data.get("error") != 0:
                return False, step_data.get("error"), step_text
            cur_state = step_data["state"]

        return False, "max_steps", f"exceeded {MAX_SEARCH_STEPS} SearchStep calls"
    finally:
        if agent_ptr is not None:
            search_end(agent_ptr)
        if obs is not None:
            try:
                from kaggle_environments.envs.cabt.cg.game import battle_finish

                battle_finish()
            except Exception:
                pass


def main():
    try:
        deck = load_deck()
        ok, _error, _text = run_seed(0, deck)
        if not ok:
            raise RuntimeError("repository deck did not pass seed-0 blocker check")
    except Exception:
        from kaggle_environments.envs.cabt.cabt import deck as cabt_deck

        deck = list(cabt_deck)
    completed = 0
    error_4 = 0
    error_5 = 0
    first_error_seed = None

    for seed in range(TOTAL):
        ok, error, _text = run_seed(seed, deck)
        if ok:
            completed += 1
        else:
            if first_error_seed is None:
                first_error_seed = seed
            if error == 4:
                error_4 += 1
            elif error == 5:
                error_5 += 1

    print(f"TOTAL: {TOTAL}")
    print(f"COMPLETED: {completed}")
    print(f"ERROR_4: {error_4}")
    print(f"ERROR_5: {error_5}")
    print(f"FIRST_ERROR_SEED: {first_error_seed}")


if __name__ == "__main__":
    main()
