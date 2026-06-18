"""Kaggle submission entry point for cabt.

The cabt engine calls ``agent(observation, configuration)`` repeatedly. The
first call has ``observation["select"] is None`` and must return the 60-card
deck. Later calls return selected option indices for the current prompt.
"""

import os
import random
import sys
import time

import torch


if "__file__" in globals():
    _HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = _HERE if os.path.isdir(os.path.join(_HERE, "models")) else os.path.dirname(_HERE)
else:
    ROOT = os.getcwd()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent import greedy
from agent import search_api
from agent.features import extract_features
from agent.mcts import DeterminizedMCTS, legal_actions_from_state
from agent.value_net import ValueNet


ITERATIONS = 500
C_PUCT = 1.4
TIME_LIMIT_MS = 1500

_MCTS = None
_VALUE_NET = None


def _load_value_net():
    global _VALUE_NET
    if _VALUE_NET is not None:
        return _VALUE_NET

    checkpoint_path = os.path.join(ROOT, "models", "value_net_best.pt")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model = ValueNet(int(checkpoint["input_dim"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    model.feature_keys = checkpoint["feature_keys"]
    model.feature_mean = torch.as_tensor(checkpoint["mean"], dtype=torch.float32)
    model.feature_std = torch.as_tensor(checkpoint["std"], dtype=torch.float32)
    _VALUE_NET = model
    return _VALUE_NET


def _get_mcts():
    global _MCTS
    if _MCTS is None:
        _MCTS = DeterminizedMCTS(
            search_api=search_api,
            value_net=_load_value_net(),
            features_fn=extract_features,
            iterations=ITERATIONS,
            c_puct=C_PUCT,
            time_limit_ms=TIME_LIMIT_MS,
        )
    return _MCTS


def _fallback(observation, configuration, legal_actions=None):
    try:
        action = greedy.agent(observation, configuration)
        if legal_actions is None:
            return action
        legal = {tuple(a) for a in legal_actions}
        if tuple(action) in legal:
            return action
    except Exception:
        pass

    if legal_actions:
        return list(random.choice(legal_actions))
    return 0


def agent(observation, configuration=None):
    """Return a deck list during setup, otherwise a legal action selection."""
    try:
        if observation.get("select") is None:
            return greedy._load_deck(configuration)

        legal_actions = legal_actions_from_state(observation)
        if not legal_actions:
            return 0

        player = (observation.get("current") or {}).get("yourIndex", 0)
        try:
            return _get_mcts().select_action(observation, player, legal_actions)
        except Exception:
            return _fallback(observation, configuration, legal_actions)
    except Exception:
        return _fallback(observation, configuration)
