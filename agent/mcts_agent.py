"""Kaggle-compatible wrapper for DeterminizedMCTS."""

import os
import random
import sys

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent import greedy
from agent.features import extract_features
from agent.mcts import DeterminizedMCTS, legal_actions_from_state
from agent.value_net import ValueNet
try:
    from agent import search_api
except Exception:
    from explore import search_api


DEFAULT_ITERATIONS = 500
DEFAULT_C_PUCT = 1.4
DEFAULT_TIME_LIMIT_MS = None

_mcts_agent = None


class MCTSAgent:
    def __init__(self, iterations=DEFAULT_ITERATIONS, c_puct=DEFAULT_C_PUCT, time_limit_ms=DEFAULT_TIME_LIMIT_MS):
        self.value_net = self._load_value_net()
        self.mcts = DeterminizedMCTS(
            search_api=search_api,
            value_net=self.value_net,
            features_fn=extract_features,
            iterations=iterations,
            c_puct=c_puct,
            time_limit_ms=time_limit_ms,
        )

    def _load_value_net(self):
        checkpoint = torch.load(os.path.join(ROOT, "models", "value_net_best.pt"), map_location="cpu", weights_only=False)
        model = ValueNet(int(checkpoint["input_dim"]))
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        model.feature_keys = checkpoint["feature_keys"]
        model.feature_mean = torch.as_tensor(checkpoint["mean"], dtype=torch.float32)
        model.feature_std = torch.as_tensor(checkpoint["std"], dtype=torch.float32)
        return model

    def select_action(self, state, player, legal_actions):
        return self.mcts.select_action(state, player, legal_actions)


def _deck(config=None):
    try:
        return greedy._load_deck(config)
    except Exception:
        from kaggle_environments.envs.cabt.cabt import deck as engine_deck

        return list(engine_deck)


def agent(obs, config=None):
    global _mcts_agent
    if obs["select"] is None:
        return _deck(config)
    if not (obs.get("select") or {}).get("option"):
        return []
    if _mcts_agent is None:
        _mcts_agent = MCTSAgent()
    legal_actions = legal_actions_from_state(obs)
    player = (obs.get("current") or {}).get("yourIndex", 0)
    try:
        return _mcts_agent.select_action(obs, player, legal_actions)
    except Exception:
        try:
            action = greedy.agent(obs, config)
            if tuple(action) in {tuple(a) for a in legal_actions}:
                return action
        except Exception:
            pass
        return list(random.choice(legal_actions)) if legal_actions else []
