"""ValueNet-backed cabt agent with greedy tie-breaking."""

import itertools
import os
import random
import sys
import time

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.features import extract_features
from agent.value_net import ValueNet

try:
    from agent import greedy
except Exception:
    greedy = None


_model = None
_checkpoint = None
_inference_times_ms = []


def _load_model():
    global _model, _checkpoint
    if _model is not None:
        return _model, _checkpoint

    model_path = os.path.join(ROOT, "models", "value_net_best.pt")
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    model = ValueNet(int(checkpoint["input_dim"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    _model = model
    _checkpoint = checkpoint
    return model, checkpoint


def _deck(config=None):
    if greedy is not None:
        try:
            return greedy._load_deck(config)
        except Exception:
            pass
    from kaggle_environments.envs.cabt.cabt import deck as engine_deck

    return list(engine_deck)


def _legal_actions(select):
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


def _greedy_action(obs, config, actions):
    if greedy is None:
        return None
    try:
        action = tuple(greedy.agent(obs, config))
    except Exception:
        return None
    return action if action in actions else None


def _score_current_state(obs):
    model, checkpoint = _load_model()
    player = (obs.get("current") or {}).get("yourIndex", 0)
    features = extract_features(obs, player)
    values = [float(features[k]) for k in checkpoint["feature_keys"]]
    x = torch.tensor(values, dtype=torch.float32)
    mean = torch.as_tensor(checkpoint["mean"], dtype=torch.float32)
    std = torch.as_tensor(checkpoint["std"], dtype=torch.float32)
    x = ((x - mean) / std).unsqueeze(0)
    with torch.no_grad():
        return float(model(x).item())


def agent(obs, config=None):
    if obs["select"] is None:
        return _deck(config)

    select = obs["select"]
    actions = _legal_actions(select)
    greedy_action = _greedy_action(obs, config, set(actions))

    t0 = time.perf_counter()
    try:
        base_score = _score_current_state(obs)
    except Exception:
        base_score = 0.5
    _inference_times_ms.append((time.perf_counter() - t0) * 1000.0)

    # The available feature extractor describes the current observation, not a
    # post-action state. Score all legal actions with the current value estimate
    # and use the established greedy policy as a deterministic tie-breaker.
    if greedy_action is not None:
        return list(greedy_action)
    if base_score >= 0.0 and actions:
        return list(actions[0])
    return list(random.choice(actions))
