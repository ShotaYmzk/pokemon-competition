#!/usr/bin/env python3
"""Generate random-vs-random self-play logs as JSONL."""

import itertools
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.features import extract_features
from kaggle_environments.envs.cabt.cabt import deck as cabt_deck
from kaggle_environments.envs.cabt.cg.game import battle_finish, battle_select, battle_start


N_MATCHES = 10000
PROGRESS_EVERY = 1000
OUT_PATH = os.path.join("logs", "self_play_10k.jsonl")


def legal_actions(select):
    options = select.get("option") or []
    n_options = len(options)
    min_count = select.get("minCount", 0)
    max_count = select.get("maxCount", 1)
    lo = min(max(min_count, 1 if n_options else 0), n_options)
    hi = min(max_count, n_options)
    if hi < lo:
        return [()]

    actions = []
    for count in range(lo, hi + 1):
        actions.extend(itertools.combinations(range(n_options), count))
    return actions or [()]


def play_match(match_id, rng, deck):
    obs, start_data = battle_start(deck, deck)
    if obs is None:
        return None, f"battle_start errorPlayer={start_data.errorPlayer} errorType={start_data.errorType}"

    rows = []
    step = 0
    try:
        while True:
            current = obs.get("current") or {}
            result = current.get("result", -1)
            if result in (0, 1, 2):
                for row in rows:
                    row["result"] = result
                return rows, None

            select = obs.get("select")
            if select is None:
                action = deck
            else:
                player = current.get("yourIndex", 0)
                actions = legal_actions(select)
                action_taken = rng.randrange(len(actions))
                action_tuple = actions[action_taken]
                action = list(action_tuple)
                rows.append(
                    {
                        "match_id": match_id,
                        "step": step,
                        "player": player,
                        "features": extract_features(obs, player),
                        "action_taken": action_taken,
                        "n_actions": len(actions),
                        "result": None,
                    }
                )
                step += 1

            obs = battle_select(action)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            battle_finish()
        except Exception:
            pass


def main():
    n_matches = int(sys.argv[1]) if len(sys.argv) > 1 else N_MATCHES
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    deck = list(cabt_deck)
    rng = random.Random(0)
    errors = {}
    completed = 0
    attempts = 0
    total_rows = 0
    start = time.time()

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        while completed < n_matches:
            rows, error = play_match(completed, rng, deck)
            attempts += 1
            if error is not None:
                errors[error] = errors.get(error, 0) + 1
                continue

            for row in rows:
                out.write(json.dumps(row, separators=(",", ":")) + "\n")
            total_rows += len(rows)
            completed += 1

            if completed % PROGRESS_EVERY == 0:
                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 else 0.0
                eta = (n_matches - completed) / rate if rate > 0 else 0.0
                print(
                    f"Progress: {completed}/{n_matches} matches | "
                    f"elapsed: {elapsed:.1f}s | eta: {eta:.1f}s",
                    flush=True,
                )

    size = os.path.getsize(OUT_PATH)
    print(f"OUTPUT: {OUT_PATH}")
    print(f"FILE_SIZE_BYTES: {size}")
    print(f"LINES: {total_rows}")
    print(f"COMPLETED_MATCHES: {completed}")
    print(f"SKIPPED_MATCHES: {attempts - completed}")
    print(f"SKIP_REASONS: {json.dumps(errors, ensure_ascii=False, sort_keys=True)}")
    print("EXTRACT_FEATURES_SIGNATURE: extract_features(state, player)")


if __name__ == "__main__":
    main()
