#!/usr/bin/env python3
"""Task A: harness to run N games between two agent module paths via kaggle_environments.

Usage:
    python explore/run_match.py [agent1_path] [agent2_path] [N] [seed]

Defaults to agent/main.py vs agent/main.py, N=10, seed=0.

Reports win/draw rates, avg steps/game, avg wall-clock/game, and
min/median/max wall-clock per step (measured as elapsed/num_steps per game,
since kaggle_environments doesn't expose per-step timestamps directly).
"""

import os
import statistics
import sys
import time

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments import make


def run_match(agent1_path, agent2_path, n_games=10, seed=0):
    wins = [0, 0]
    draws = 0
    errors = 0
    steps_per_game = []
    wallclock_per_game = []
    wallclock_per_step = []  # per-game average step time, one entry per game

    for i in range(n_games):
        env = make("cabt", debug=False)
        # Alternate seed deterministically per game so games differ but the run is reproducible.
        game_seed = seed + i
        if hasattr(env, "configuration"):
            try:
                env.configuration["randomSeed"] = game_seed
            except Exception:
                pass

        t0 = time.time()
        try:
            result = env.run([agent1_path, agent2_path])
        except Exception as e:
            print(f"[game {i}] FAILED: {e}")
            errors += 1
            continue
        elapsed = time.time() - t0

        n_steps = len(result)
        steps_per_game.append(n_steps)
        wallclock_per_game.append(elapsed)
        wallclock_per_step.append(elapsed / max(1, n_steps))

        last = result[-1]
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
        print(
            f"wallclock/step (per-game avg): "
            f"min={min(wallclock_per_step):.4f}s "
            f"median={statistics.median(wallclock_per_step):.4f}s "
            f"max={max(wallclock_per_step):.4f}s"
        )
    return {
        "wins": wins,
        "draws": draws,
        "errors": errors,
        "n_completed": n_completed,
        "steps_per_game": steps_per_game,
        "wallclock_per_game": wallclock_per_game,
        "wallclock_per_step": wallclock_per_step,
    }


if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_agent = os.path.join(repo_root, "agent", "main.py")

    agent1 = sys.argv[1] if len(sys.argv) > 1 else default_agent
    agent2 = sys.argv[2] if len(sys.argv) > 2 else default_agent
    n_games = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0

    run_match(agent1, agent2, n_games, seed)
