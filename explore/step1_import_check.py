#!/usr/bin/env python3
"""STEP 1: cabt import check and basic API availability"""

import ctypes
import json
import sys
import os

# Add cabt cg to path
CABT_DIR = os.path.join(
    os.path.dirname(sys.executable),
    "..", "lib", "python3.11", "site-packages",
    "kaggle_environments", "envs", "cabt"
)

print("=== STEP 1: Import Check ===")

try:
    from kaggle_environments.envs.cabt.cg.sim import lib, Battle, StartData, SerialData
    print("[OK] from kaggle_environments.envs.cabt.cg.sim import lib")
except Exception as e:
    print(f"[FAIL] sim import: {e}")
    sys.exit(1)

try:
    from kaggle_environments.envs.cabt.cg.game import (
        battle_start, battle_finish, battle_select, visualize_data
    )
    print("[OK] game functions imported")
except Exception as e:
    print(f"[FAIL] game import: {e}")
    sys.exit(1)

print("\n=== Available C functions in libcg.so ===")
funcs = ["AllCard", "AllAttack", "SearchBegin", "SearchStep", "SearchEnd",
         "SearchRelease", "AgentStart", "BattleStart", "BattleFinish",
         "GameInitialize", "GetBattleData", "Select", "VisualizeData"]
for f in funcs:
    try:
        fn = getattr(lib, f)
        print(f"[OK] lib.{f} -> {fn}")
    except Exception as e:
        print(f"[MISS] lib.{f}: {e}")

print("\n=== STEP 1 Complete ===")
