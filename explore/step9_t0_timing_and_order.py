#!/usr/bin/env python3
"""T0: (1) measure raw SearchStep call latency / throughput, and (2) decisive
experiment on whether SearchBegin's hidden-info arrays are order-sensitive or
only composition-sensitive (same multiset, two different orderings -> same
behavior under an identical action sequence, or not).

Usage: python explore/step9_t0_timing_and_order.py
"""
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

from explore.search_api import agent_start, search_begin, search_end, search_step
from explore.step6_forward_model_validation import (
    load_deck,
    advance_to_midgame,
    sample_determinized_hidden_state,
)


def t0_1_timing(deck, n_seeds=15, max_steps_per_seed=60):
    """Measure wall-clock per SearchStep call across many seeds/positions."""
    all_times = []
    n_errors = 0
    n_calls = 0
    for seed in range(n_seeds):
        try:
            obs, _ = advance_to_midgame(deck, seed=seed, min_turn=2)
        except Exception:
            continue
        cur = obs["current"]
        your_index = cur["yourIndex"]
        opp_index = 1 - your_index
        sbi_bytes = (obs.get("search_begin_input") or "").encode("ascii")
        rng = random.Random(seed)
        try:
            arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng)
        except ValueError:
            battle_finish()
            continue

        agent_ptr = agent_start()
        t0 = time.perf_counter()
        begin_data, begin_text = search_begin(
            agent_ptr, sbi_bytes,
            your_deck=arrays["your_deck"], your_prize=arrays["your_prize"],
            opp_deck=arrays["opp_deck"], opp_prize=arrays["opp_prize"],
            opp_hand=arrays["opp_hand"], opp_active=arrays["opp_active"],
            deck_filler=deck,
        )
        dt = time.perf_counter() - t0
        all_times.append(dt)
        n_calls += 1
        if begin_data.get("error") != 0:
            search_end(agent_ptr)
            battle_finish()
            n_errors += 1
            continue

        cur_state = begin_data["state"]
        for _ in range(max_steps_per_seed):
            obs_s = cur_state["observation"]
            if obs_s["current"].get("result", -1) >= 0:
                break
            sel = obs_s.get("select")
            if not sel or not sel.get("option"):
                break
            opts = sel.get("option", [])
            mc = min(sel.get("maxCount", 1), len(opts))
            mc = max(mc, sel.get("minCount", 0))
            mc = min(mc, len(opts))
            action = random.sample(range(len(opts)), mc) if mc > 0 else []

            t0 = time.perf_counter()
            step_data, step_text = search_step(agent_ptr, 0, action, select=sel)
            dt = time.perf_counter() - t0
            all_times.append(dt)
            n_calls += 1
            if step_data.get("error") != 0:
                n_errors += 1
                break
            cur_state = step_data["state"]

        search_end(agent_ptr)
        battle_finish()

    print("=== T0-1: SearchStep/SearchBegin latency ===")
    print(f"n_calls={n_calls} n_errors_terminated_chain={n_errors}")
    if all_times:
        print(f"min={min(all_times)*1000:.4f}ms median={statistics.median(all_times)*1000:.4f}ms "
              f"mean={statistics.mean(all_times)*1000:.4f}ms max={max(all_times)*1000:.4f}ms")
        calls_per_sec = 1.0 / statistics.mean(all_times)
        print(f"throughput: ~{calls_per_sec:.0f} SearchStep/SearchBegin calls per second (single-threaded)")
        avg_remaining_moves = 70  # ~ from STEP8 timing data (avg ~79 steps/game observed)
        budget_per_move_sec = 3000.0 / avg_remaining_moves
        print(f"budget/move (3000s / ~{avg_remaining_moves} moves) = {budget_per_move_sec:.1f}s/move "
              f"-> ~{budget_per_move_sec * calls_per_sec:.0f} SearchStep-equivalent calls available per move")
    return all_times


def t0_2_order_vs_composition(deck, seed=3, n_action_steps=10):
    """Decisive experiment: same multiset, two different (shuffled) orderings of
    your_deck/opp_deck passed to SearchBegin. Drive an IDENTICAL action-index
    sequence through both resulting search chains and compare the resulting
    SelectData sequences (context/type/minCount/maxCount/option count/prize
    counts/terminal result) at every step. If they ever diverge in a way that
    isn't explainable purely by an RNG draw (coin flip / shuffle / draw order
    that SearchBegin's own internal RNG performs identically regardless of our
    array order), order matters. If they track identically, order is irrelevant
    and only composition (the multiset) needs to be correct.
    """
    obs, _ = advance_to_midgame(deck, seed=seed, min_turn=2)
    cur = obs["current"]
    your_index = cur["yourIndex"]
    opp_index = 1 - your_index
    sbi_bytes = (obs.get("search_begin_input") or "").encode("ascii")
    rng = random.Random(seed)
    arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng)
    battle_finish()

    def run_chain(your_deck_order, opp_deck_order, action_rng_seed):
        obs2, _ = advance_to_midgame(deck, seed=seed, min_turn=2)
        sbi2 = (obs2.get("search_begin_input") or "").encode("ascii")
        agent_ptr = agent_start()
        begin_data, begin_text = search_begin(
            agent_ptr, sbi2,
            your_deck=your_deck_order, your_prize=arrays["your_prize"],
            opp_deck=opp_deck_order, opp_prize=arrays["opp_prize"],
            opp_hand=arrays["opp_hand"], opp_active=arrays["opp_active"],
            deck_filler=deck,
        )
        trace = []
        if begin_data.get("error") != 0:
            search_end(agent_ptr)
            battle_finish()
            return trace, begin_data.get("error")

        cur_state = begin_data["state"]
        action_rng = random.Random(action_rng_seed)
        for _ in range(n_action_steps):
            obs_s = cur_state["observation"]
            sel = obs_s.get("select")
            result = obs_s["current"].get("result", -1)
            prizes = [len(p["prize"]) for p in obs_s["current"]["players"]]
            trace.append({
                "result": result,
                "prizes": prizes,
                "sel_context": sel.get("context") if sel else None,
                "sel_type": sel.get("type") if sel else None,
                "n_options": len(sel.get("option", [])) if sel else None,
            })
            if result >= 0 or not sel or not sel.get("option"):
                break
            opts = sel.get("option", [])
            mc = min(sel.get("maxCount", 1), len(opts))
            mc = max(mc, sel.get("minCount", 0))
            mc = min(mc, len(opts))
            action = action_rng.sample(range(len(opts)), mc) if mc > 0 else []
            step_data, step_text = search_step(agent_ptr, 0, action, select=sel)
            if step_data.get("error") != 0:
                trace.append({"error": step_data.get("error")})
                break
            cur_state = step_data["state"]

        search_end(agent_ptr)
        battle_finish()
        return trace, 0

    # Order A: as sampled. Order B: same multiset, fully shuffled differently.
    your_deck_b = list(arrays["your_deck"])
    opp_deck_b = list(arrays["opp_deck"])
    shuf_rng = random.Random(999)
    shuf_rng.shuffle(your_deck_b)
    shuf_rng.shuffle(opp_deck_b)
    assert sorted(your_deck_b) == sorted(arrays["your_deck"])
    assert sorted(opp_deck_b) == sorted(arrays["opp_deck"])

    trace_a, err_a = run_chain(arrays["your_deck"], arrays["opp_deck"], action_rng_seed=42)
    trace_b, err_b = run_chain(your_deck_b, opp_deck_b, action_rng_seed=42)

    print("\n=== T0-2: order vs composition ===")
    print(f"SearchBegin error A={err_a} B={err_b}")
    print(f"trace A: {trace_a}")
    print(f"trace B: {trace_b}")
    same = trace_a == trace_b
    print(f"\nIDENTICAL trace under identical action sequence, different deck array order: {same}")
    if same:
        print("CONCLUSION: order appears IRRELEVANT -- only composition (the multiset) need be legal.")
    else:
        print("CONCLUSION: order MATTERS -- traces diverged with the same composition+actions but different order.")
    return same


if __name__ == "__main__":
    deck = load_deck()
    t0_1_timing(deck)
    t0_2_order_vs_composition(deck)
