#!/usr/bin/env python3
"""Empirical investigation of cabt obs structure: prize semantics, result field, yourIndex."""
import json
import os
import random
import copy

os.environ.setdefault("KAGGLE_ENVIRONMENTS_SUPPRESS_LOGS", "1")

from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_deck():
    with open(os.path.join(REPO, "agent", "deck.csv")) as f:
        deck = [int(l.strip()) for l in f if l.strip()]
    assert len(deck) == 60
    return deck


def hp_list(player):
    out = []
    for j, a in enumerate(player.get("active") or []):
        if a:
            out.append((f"active{j}", a.get("hp")))
    for i, b in enumerate(player.get("bench") or []):
        if b:
            out.append((f"bench{i}", b.get("hp")))
    return out


def run_game(deck, seed, max_steps=300, verbose=True):
    random.seed(seed)
    obs, start_data = battle_start(deck, deck)
    if obs is None:
        print("battle_start failed:", start_data)
        return None

    if verbose:
        print("\n--- initial obs top-level keys ---", list(obs.keys()))
        cur0 = obs["current"]
        print("current keys:", list(cur0.keys()))
        print("players[0] keys:", list(cur0["players"][0].keys()))
        print("select keys:", list(obs["select"].keys()) if obs["select"] else None)
        print(json.dumps({"yourIndex": cur0["yourIndex"], "result": cur0["result"], "turn": cur0.get("turn")}, indent=2))

    cur0 = obs["current"]
    prev_hp = [dict(hp_list(cur0["players"][0])), dict(hp_list(cur0["players"][1]))]
    prev_prize = [copy.deepcopy(cur0["players"][0]["prize"]), copy.deepcopy(cur0["players"][1]["prize"])]
    your_index_history = []
    step = 0
    result = -1

    while step < max_steps:
        cur = obs["current"]
        result = cur["result"]
        your_index_history.append(cur["yourIndex"])
        if result != -1:
            break

        sel = obs.get("select")
        if sel is None:
            action = deck
        else:
            opts = sel.get("option", [])
            mc = sel.get("maxCount", 1)
            mc = min(mc, len(opts))
            mc = max(mc, sel.get("minCount", 0))
            action = random.sample(range(len(opts)), mc) if opts else []

        obs = battle_select(action)
        step += 1

        cur = obs["current"]
        if step % 10 == 0 and verbose:
            for i in (0, 1):
                p = cur["players"][i]["prize"]
                non_null = sum(1 for x in p if x is not None)
                null_ct = sum(1 for x in p if x is None)
                print(f"step={step} player{i} prize len={len(p)} non_null={non_null} null={null_ct} result={cur['result']}")

        for i in (0, 1):
            cur_hp = dict(hp_list(cur["players"][i]))
            for slot, hp in cur_hp.items():
                old = prev_hp[i].get(slot)
                if old is not None and old > 0 and hp is not None and hp <= 0:
                    print(f"\n*** KO detected at step={step}: player{i} slot={slot} hp {old}->{hp} ***")
                    print(f"BEFORE this state, player0 prize: {json.dumps(prev_prize[0])[:600]}")
                    print(f"BEFORE this state, player1 prize: {json.dumps(prev_prize[1])[:600]}")
                    print(f"AFTER this state,  player0 prize: {json.dumps(cur['players'][0]['prize'])[:600]}")
                    print(f"AFTER this state,  player1 prize: {json.dumps(cur['players'][1]['prize'])[:600]}")
            prev_hp[i] = cur_hp
        prev_prize = [copy.deepcopy(cur["players"][0]["prize"]), copy.deepcopy(cur["players"][1]["prize"])]

    print(f"\n=== Game ended (or max_steps) at step={step}, result={result} ===")
    print("yourIndex history (last 20):", your_index_history[-20:])
    print("unique yourIndex values seen:", set(your_index_history))
    cur = obs["current"]
    for i in (0, 1):
        p = cur["players"][i]["prize"]
        print(f"FINAL player{i} prize: len={len(p)} non_null={sum(1 for x in p if x is not None)} null={sum(1 for x in p if x is None)}")
        print(f"  full: {json.dumps(p)[:600]}")

    for i in (0, 1):
        pl = cur["players"][i]
        if "result" in pl:
            print(f"player{i} has own 'result' field: {pl['result']}")
    print(f"current.result (global) = {cur['result']}")

    battle_finish()
    return result


if __name__ == "__main__":
    deck = load_deck()
    results = []
    for seed in [1, 2, 3, 4, 5]:
        print(f"\n\n########## GAME seed={seed} ##########")
        r = run_game(deck, seed, verbose=(seed == 1))
        results.append(r)
    print("\n\n=== SUMMARY across seeds ===", results)
