import os
import sys
import random

_deck = None

def _deck_candidates(config=None):
    candidates = []

    raw_path = None
    if config is not None:
        try:
            raw_path = config.get("__raw_path__")
        except AttributeError:
            raw_path = getattr(config, "__raw_path__", None)
    if raw_path:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(raw_path)), "deck.csv"))

    if "__file__" in globals():
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv"))

    candidates.append(os.path.join(os.getcwd(), "deck.csv"))
    candidates.append(os.path.join(os.getcwd(), "agent", "deck.csv"))
    candidates.append("/kaggle_simulations/agent/deck.csv")

    for p in sys.path:
        candidates.append(os.path.join(p, "deck.csv"))

    return candidates


def _load_deck(config=None):
    global _deck
    if _deck is not None:
        return _deck
    seen = set()
    candidates = _deck_candidates(config)
    for deck_path in candidates:
        if deck_path in seen:
            continue
        seen.add(deck_path)
        if os.path.exists(deck_path):
            with open(deck_path) as f:
                _deck = [int(line.strip()) for line in f if line.strip()]
            assert len(_deck) == 60, f"deck.csv must have 60 cards, got {len(_deck)}"
            return _deck
    raise FileNotFoundError(f"deck.csv not found in: {candidates}")


def agent(obs, config=None):
    # Deck selection phase: obs["select"] is None
    if obs["select"] is None:
        return _load_deck(config)

    # Normal turn: pick maxCount random options from available options
    options = obs["select"]["option"]
    max_count = obs["select"]["maxCount"]
    return random.sample(list(range(len(options))), max_count)
