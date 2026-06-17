#!/usr/bin/env python3
"""STEP 3 prep: inspect the default deck in cabt.py and understand card schema"""

import ctypes
import json

from kaggle_environments.envs.cabt.cg.sim import lib

lib.AllCard.restype = ctypes.c_char_p
lib.AllCard.argtypes = []
cards_raw = json.loads(lib.AllCard().decode())

# Build id -> card map
if isinstance(cards_raw, list):
    card_map = {c["cardId"]: c for c in cards_raw}
else:
    card_map = {int(k): v for k, v in cards_raw.items()}

# Default deck from cabt.py
default_deck = [
    721,721,722,722,722,722,723,723,723,723,
    1092,1121,1121,1145,1145,1163,1163,
    1219,1219,1219,1219,1227,1227,1227,1227,
    1262,1262,
    3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,
    3,3,3,3,3,3,3,3,3,3,3,3,3,3
]
print(f"Default deck has {len(default_deck)} cards")

print("\n--- Unique cards in default deck ---")
for cid in sorted(set(default_deck)):
    c = card_map.get(cid)
    if c:
        print(f"  ID={cid:5d} name={c['name']!r:40s} type={c['cardType']} pokemonType={c['pokemonType']} hp={c['hp']}")
    else:
        print(f"  ID={cid:5d} [NOT FOUND]")

# Count cards by type
print("\n--- Card type distribution ---")
from collections import Counter
type_names = {0:"Unknown",1:"Pokemon",2:"Trainer",3:"Supporter",4:"Stadium",5:"Energy",6:"Item",7:"Tool"}
cnt = Counter()
for c in card_map.values():
    cnt[c["cardType"]] += 1
for k, v in sorted(cnt.items()):
    print(f"  type {k} ({type_names.get(k,'?')}): {v} cards")

# Show a Pokemon card example (type=1)
pokemon_cards = [c for c in card_map.values() if c["cardType"] == 1 and c["hp"] > 0]
if pokemon_cards:
    print(f"\n--- Sample Pokemon card ---")
    print(json.dumps(pokemon_cards[0], ensure_ascii=False, indent=2))
