#!/usr/bin/env python3
"""STEP 10: measure win rate of agent/mcts.py vs agent/greedy.py across
several mcts_max_depth values, to test the hypothesis (findings.md /
session recap) that max_depth=30 is too shallow to reach into the
opponent's turn, and that this -- not the negamax sign fix -- is the
dominant cause of the "more search -> worse win rate" inversion.

Usage:
    python explore/step10_max_depth_experiment.py [n_games_per_depth] [depths...]

Defaults to 20 games per depth, depths = 5 10 20 50.
"""
import os
import sys
import time

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments import make
from kaggle_environments.core import Agent, act_agent

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCTS_PATH = os.path.join(REPO_ROOT, "agent", "mcts.py")
GREEDY_PATH = os.path.join(REPO_ROOT, "agent", "greedy.py")


def run_one_game(mcts_max_depth, mcts_side, seed):
    """mcts_side: 0 or 1 -- which player index runs mcts.py (the other runs greedy.py)."""
    env = make("cabt", debug=False)
    env.configuration["randomSeed"] = seed
    env.configuration["mcts_max_depth"] = mcts_max_depth
    env.configuration["mcts_max_sims"] = 300
    env.configuration["mcts_seconds"] = 1.0

    env.reset(2)
    paths = [MCTS_PATH, GREEDY_PATH] if mcts_side == 0 else [GREEDY_PATH, MCTS_PATH]
    agents = [Agent(p, env) for p in paths]
    get_shared_state = getattr(env, "_Environment__get_shared_state")

    while not env.done:
        actions, logs = [], []
        for i, agent in enumerate(agents):
            shared_state = get_shared_state(i)
            action, log = act_agent((agent, shared_state, env.configuration, None))
            actions.append(action)
            logs.append(log)
        env.step(actions, logs)

    last = env.steps[-1]
    r_mcts = last[mcts_side]["reward"]
    r_greedy = last[1 - mcts_side]["reward"]
    return r_mcts, r_greedy, len(env.steps)


def run_depth_sweep(depths, n_games, seed0=0):
    results = {}
    for depth in depths:
        wins = draws = losses = errors = 0
        t0 = time.time()
        for i in range(n_games):
            seed = seed0 + i
            mcts_side = i % 2  # alternate who goes first to cancel first-move advantage
            try:
                r_mcts, r_greedy, n_steps = run_one_game(depth, mcts_side, seed)
            except Exception as e:
                print(f"  [depth={depth} game={i}] FAILED: {e}")
                errors += 1
                continue
            if r_mcts == 1:
                wins += 1
            elif r_greedy == 1:
                losses += 1
            else:
                draws += 1
            print(f"  [depth={depth} game={i}] mcts_side={mcts_side} r_mcts={r_mcts} r_greedy={r_greedy} steps={n_steps}")
        elapsed = time.time() - t0
        completed = n_games - errors
        win_rate = wins / completed if completed else float("nan")
        results[depth] = {
            "wins": wins, "draws": draws, "losses": losses, "errors": errors,
            "completed": completed, "win_rate": win_rate, "elapsed": elapsed,
        }
        print(f"depth={depth}: win_rate={win_rate:.1%} ({wins}/{completed}) "
              f"draws={draws} losses={losses} errors={errors} elapsed={elapsed:.1f}s\n")
    return results


if __name__ == "__main__":
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    depths = [int(a) for a in sys.argv[2:]] if len(sys.argv) > 2 else [5, 10, 20, 50]

    print(f"Running mcts(max_depth=D) vs greedy, {n_games} games/depth, depths={depths}\n")
    results = run_depth_sweep(depths, n_games)

    print("\n=== summary ===")
    print(f"{'depth':>6} | {'win_rate':>9} | {'W':>3} {'D':>3} {'L':>3} {'err':>3} | {'elapsed':>8}")
    for depth, r in results.items():
        print(f"{depth:>6} | {r['win_rate']:>8.1%} | {r['wins']:>3} {r['draws']:>3} {r['losses']:>3} {r['errors']:>3} | {r['elapsed']:>7.1f}s")
