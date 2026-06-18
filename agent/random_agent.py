"""Uniform-random legal-action baseline."""

import random

from agent import greedy


def agent(obs, config=None):
    if obs["select"] is None:
        try:
            return greedy._load_deck(config)
        except Exception:
            from kaggle_environments.envs.cabt.cabt import deck as engine_deck

            return list(engine_deck)

    select = obs["select"]
    options = select.get("option") or []
    n_options = len(options)
    min_count = select.get("minCount", 0)
    max_count = select.get("maxCount", 1)
    lo = min(max(min_count, 1 if n_options else 0), n_options)
    hi = min(max_count, n_options)
    if hi < lo or hi <= 0:
        return []
    count = random.randint(lo, hi)
    return sorted(random.sample(range(n_options), count))
