#!/usr/bin/env python3
"""STEP 4: Local self-play between two random agents"""

import sys
import os
import time

# Suppress INFO logs
os.environ["KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS"] = "1"

from kaggle_environments import make

print("=== STEP 4: Local Self-Play ===\n")

# Load the agent from main.py
agent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent", "main.py"))
print(f"Agent: {agent_path}")

try:
    env = make("cabt", debug=False)
    print(f"[OK] Environment created: cabt")
    print(f"     episodeSteps={env.specification.configuration.episodeSteps}")
    print(f"     actTimeout={env.specification.configuration.actTimeout}")
    print(f"     runTimeout={env.specification.configuration.runTimeout}")
except Exception as e:
    print(f"[FAIL] make('cabt'): {e}")
    sys.exit(1)

print("\nRunning 1 game (random vs random) ...")
t0 = time.time()

try:
    result = env.run([agent_path, agent_path])
    elapsed = time.time() - t0
    print(f"[OK] Game completed in {elapsed:.1f}s")
    print(f"     Steps: {len(result)}")

    last = result[-1]
    p0 = last[0]
    p1 = last[1]
    print(f"     Player 0 reward: {p0['reward']}  status: {p0['status']}")
    print(f"     Player 1 reward: {p1['reward']}  status: {p1['status']}")

    if p0['reward'] == 1:
        print("     Winner: Player 0")
    elif p1['reward'] == 1:
        print("     Winner: Player 1")
    else:
        print("     Result: Draw")

except Exception as e:
    import traceback
    print(f"[FAIL] Game failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n=== STEP 4 Complete ===")
