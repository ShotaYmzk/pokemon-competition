#!/usr/bin/env python3
"""Task A: harness to run N games between two agent module paths via kaggle_environments.

Usage:
    python explore/run_match.py [agent1_path] [agent2_path] [N] [seed]

Defaults to agent/main.py vs agent/main.py, N=10, seed=0.

Reports win/draw rates, avg steps/game, avg wall-clock/game, and
TRUE per-action wall-clock timing (min/median/max), measured by manually
driving env.reset()/act_agent()/env.step() instead of relying on env.run(),
since env.run() does not expose per-step timestamps. This calibrates search
budget for a future MCTS agent against the runTimeout=3000s/game limit.
"""

import os
import statistics
import sys
import time

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments import make
from kaggle_environments.core import Agent, act_agent


def run_one_game_instrumented(agent1_path, agent2_path, seed=0):
    """Manually drive one game via env.reset()/act_agent()/env.step(), timing each action.

    Returns (steps_list, step_times) where step_times is a flat list of per-action
    wall-clock durations (one entry per agent action call, both players combined).
    """
    env = make("cabt", debug=False)
    if hasattr(env, "configuration"):
        try:
            env.configuration["randomSeed"] = seed
        except Exception:
            pass

    env.reset(2)
    agents = [Agent(agent1_path, env), Agent(agent2_path, env)]

    get_shared_state = getattr(env, "_Environment__get_shared_state")

    step_times = []
    t_game0 = time.time()
    while not env.done:
        actions = []
        logs = []
        for i, agent in enumerate(agents):
            shared_state = get_shared_state(i)
            t0 = time.perf_counter()
            action, log = act_agent((agent, shared_state, env.configuration, None))
            dt = time.perf_counter() - t0
            step_times.append(dt)
            actions.append(action)
            logs.append(log)
        env.step(actions, logs)
    game_elapsed = time.time() - t_game0

    return env.steps, step_times, game_elapsed


def run_match(agent1_path, agent2_path, n_games=10, seed=0, instrument_steps=True):
    wins = [0, 0]
    draws = 0
    errors = 0
    steps_per_game = []
    wallclock_per_game = []
    all_step_times = []  # flat list across all games, one entry per individual action

    for i in range(n_games):
        game_seed = seed + i
        try:
            if instrument_steps:
                steps, step_times, elapsed = run_one_game_instrumented(agent1_path, agent2_path, game_seed)
                all_step_times.extend(step_times)
            else:
                env = make("cabt", debug=False)
                t0 = time.time()
                steps = env.run([agent1_path, agent2_path])
                elapsed = time.time() - t0
        except Exception as e:
            print(f"[game {i}] FAILED: {e}")
            errors += 1
            continue

        n_steps = len(steps)
        steps_per_game.append(n_steps)
        wallclock_per_game.append(elapsed)

        last = steps[-1]
        r0, r1 = last[0]["reward"], last[1]["reward"]
        if r0 == 1:
            wins[0] += 1
        elif r1 == 1:
            wins[1] += 1
        else:
            draws += 1

        print(f"[game {i}] steps={n_steps} elapsed={elapsed:.2f}s r0={r0} r1={r1}")

    n_completed = n_games - errors
    print("\n=== run_match summary ===")
    print(f"agent1={agent1_path}")
    print(f"agent2={agent2_path}")
    print(f"games requested={n_games} completed={n_completed} errors={errors}")
    if n_completed:
        print(f"agent1 win rate: {wins[0] / n_completed:.2%} ({wins[0]}/{n_completed})")
        print(f"agent2 win rate: {wins[1] / n_completed:.2%} ({wins[1]}/{n_completed})")
        print(f"draw rate:       {draws / n_completed:.2%} ({draws}/{n_completed})")
        print(f"avg steps/game:  {statistics.mean(steps_per_game):.1f}")
        print(f"avg wallclock/game: {statistics.mean(wallclock_per_game):.3f}s")
        if all_step_times:
            print(
                f"wallclock/action (per single agent decision, n={len(all_step_times)}): "
                f"min={min(all_step_times)*1000:.3f}ms "
                f"median={statistics.median(all_step_times)*1000:.3f}ms "
                f"max={max(all_step_times)*1000:.3f}ms "
                f"mean={statistics.mean(all_step_times)*1000:.3f}ms"
            )
    return {
        "wins": wins,
        "draws": draws,
        "errors": errors,
        "n_completed": n_completed,
        "steps_per_game": steps_per_game,
        "wallclock_per_game": wallclock_per_game,
        "step_times": all_step_times,
    }


if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_agent = os.path.join(repo_root, "agent", "main.py")

    agent1 = sys.argv[1] if len(sys.argv) > 1 else default_agent
    agent2 = sys.argv[2] if len(sys.argv) > 2 else default_agent
    n_games = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    run_match(agent1, agent2, n_games, seed)
