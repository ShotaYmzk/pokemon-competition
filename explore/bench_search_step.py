#!/usr/bin/env python3
"""Measure SearchStep latency on a fixed random-vs-random midgame state."""

import random
import statistics
import time

from kaggle_environments.envs.cabt.cabt import deck as engine_deck
from kaggle_environments.envs.cabt.cg.game import battle_finish, battle_select, battle_start

from explore.search_api import (
    agent_start,
    card_ids,
    first_valid_search_action,
    remaining_deck_guess,
    search_begin,
    search_end,
    search_step,
)


BUDGET_PER_MOVE_MS = int(3000 / 80 * 1000)


def _random_action(select, rng):
    options = select.get("option") or []
    n_options = len(options)
    min_count = select.get("minCount", 0)
    max_count = select.get("maxCount", 1)
    lo = min(max(min_count, 1 if n_options else 0), n_options)
    hi = min(max_count, n_options)
    if hi < lo or hi <= 0:
        return []
    count = rng.randint(lo, hi)
    return sorted(rng.sample(range(n_options), count))


def _make_position(seed=0, decisions=5):
    rng = random.Random(seed)
    deck = list(engine_deck)
    obs, start_data = battle_start(deck, deck)
    if obs is None:
        raise RuntimeError(f"battle_start failed: {start_data}")

    for _ in range(decisions):
        select = obs.get("select")
        if select is None:
            action = deck
        else:
            action = _random_action(select, rng)
        obs = battle_select(action)
        if (obs.get("current") or {}).get("result", -1) >= 0:
            raise RuntimeError("game ended before benchmark position")
    return obs, deck


def main():
    obs, deck = _make_position(seed=0, decisions=5)
    agent_ptr = agent_start()
    search_id = 0
    try:
        current = obs["current"]
        player = current["yourIndex"]
        opponent = 1 - player
        opponent_state = current["players"][opponent]
        begin_data, begin_text = search_begin(
            agent_ptr,
            (obs.get("search_begin_input") or "").encode("ascii"),
            your_deck=remaining_deck_guess(obs, player, deck),
            your_prize=[],
            opp_deck=remaining_deck_guess(obs, opponent, deck),
            opp_prize=[],
            opp_hand=card_ids(opponent_state.get("hand")),
            opp_active=card_ids(opponent_state.get("active")),
            deck_filler=deck,
        )
        if begin_data.get("error") != 0:
            raise RuntimeError(f"SearchBegin failed: {begin_text[:500]}")

        state = begin_data["state"]
        search_id = state.get("searchId", 0)
        select = state["observation"].get("select")
        action = first_valid_search_action(select)
        if not action and select and select.get("option"):
            action = [0]

        times_ms = []
        for _ in range(100):
            t0 = time.perf_counter()
            step_data, step_text = search_step(agent_ptr, search_id, action, select=select)
            times_ms.append((time.perf_counter() - t0) * 1000.0)
            if step_data.get("error") != 0:
                raise RuntimeError(f"SearchStep failed: {step_text[:500]}")

        median_ms = statistics.median(times_ms)
        p95_ms = sorted(times_ms)[int(len(times_ms) * 0.95) - 1]
        iterations = int(BUDGET_PER_MOVE_MS / median_ms) if median_ms > 0 else 0
        print(f"SEARCH_STEP_MEDIAN_MS: {median_ms:.3f}")
        print(f"SEARCH_STEP_P95_MS: {p95_ms:.3f}")
        print(f"BUDGET_PER_MOVE_MS: {BUDGET_PER_MOVE_MS}")
        print(f"ITERATIONS_IN_BUDGET: {iterations}")
    finally:
        search_end(agent_ptr, search_id)
        battle_finish()


if __name__ == "__main__":
    main()
