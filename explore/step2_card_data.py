#!/usr/bin/env python3
"""STEP 2: Card data dump - AllCard / AllAttack API"""

import ctypes
import json
import sys
import os

from kaggle_environments.envs.cabt.cg.sim import lib

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "explore")

print("=== STEP 2: Card Data Dump ===\n")

# ---- AllCard ----
lib.AllCard.restype = ctypes.c_char_p
lib.AllCard.argtypes = []

raw = lib.AllCard()
if raw is None:
    print("[FAIL] AllCard() returned None")
    sys.exit(1)

try:
    cards = json.loads(raw.decode())
    print(f"[OK] AllCard() returned {len(cards)} items")
except json.JSONDecodeError as e:
    print(f"[FAIL] JSON parse error: {e}")
    print(f"  Raw (first 200 chars): {raw[:200]}")
    sys.exit(1)

# Schema sample
if cards:
    sample = cards[0] if isinstance(cards, list) else list(cards.values())[0]
    print(f"\n--- Card schema (first entry) ---")
    print(json.dumps(sample, ensure_ascii=False, indent=2)[:2000])

    # Save all cards
    out_path = os.path.join(OUTPUT_DIR, "all_cards.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVED] {len(cards)} cards -> {out_path}")

# ---- AllAttack ----
lib.AllAttack.restype = ctypes.c_char_p
lib.AllAttack.argtypes = []

raw_atk = lib.AllAttack()
if raw_atk is None:
    print("[FAIL] AllAttack() returned None")
else:
    try:
        attacks = json.loads(raw_atk.decode())
        print(f"\n[OK] AllAttack() returned {len(attacks)} items")
        if attacks:
            sample_atk = attacks[0] if isinstance(attacks, list) else list(attacks.values())[0]
            print(f"\n--- Attack schema (first entry) ---")
            print(json.dumps(sample_atk, ensure_ascii=False, indent=2)[:1000])
        out_path2 = os.path.join(OUTPUT_DIR, "all_attacks.json")
        with open(out_path2, "w", encoding="utf-8") as f:
            json.dump(attacks, f, ensure_ascii=False, indent=2)
        print(f"[SAVED] {len(attacks)} attacks -> {out_path2}")
    except json.JSONDecodeError as e:
        print(f"[FAIL] AllAttack JSON parse: {e}")

print("\n=== STEP 2 Complete ===")
