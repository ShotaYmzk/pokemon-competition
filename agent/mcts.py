"""Determinized MCTS v0 with ValueNet leaf evaluation."""

import collections
import itertools
import math
import os
import random
import sys
import time

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent import greedy
try:
    from agent import search_api
except Exception:
    from explore import search_api


class MCTSNode:
    """A node in the SearchStep tree."""

    def __init__(self, state, parent=None, action=None):
        self.state = state
        self.parent = parent
        self.action = action
        self.children = {}
        self.visit_count = 0
        self.value_sum = 0.0
        self.is_terminal = _is_terminal_state(state)
        self.untried_actions = None


class DeterminizedMCTS:
    def __init__(
        self,
        search_api,
        value_net,
        features_fn,
        iterations: int,
        c_puct: float = 1.4,
        time_limit_ms: float = None,
        error_tolerance: float = 0.3,
    ):
        self.search_api = search_api
        self.value_net = value_net
        self.features_fn = features_fn
        self.iterations = int(iterations)
        self.c_puct = float(c_puct)
        self.time_limit_ms = time_limit_ms
        self.error_tolerance = float(error_tolerance)
        self.agent_ptr = self.search_api.agent_start()
        self.rng = random.Random()
        self.total_search_steps = 0
        self.total_search_errors = 0
        self.total_decisions = 0
        self.fallback_decisions = 0
        self.last_error_rate = 0.0
        self.last_used_fallback = False

    def select_action(self, state: dict, player: int, legal_actions: list) -> int:
        """Return the selected legal action list for the current observation."""
        self.total_decisions += 1
        self.last_used_fallback = False
        start = time.perf_counter()
        search_id = 0

        if self.time_limit_ms is not None and self.time_limit_ms <= 1:
            return self._fallback(state, legal_actions)

        try:
            if not legal_actions:
                return []
            if not state.get("search_begin_input"):
                return self._fallback(state, legal_actions)

            det = self._determinize(state, player)
            begin_data, begin_text = self.search_api.search_begin(
                self.agent_ptr,
                state["search_begin_input"].encode("ascii"),
                your_deck=det["your_deck"],
                your_prize=det["your_prize"],
                opp_deck=det["opp_deck"],
                opp_prize=det["opp_prize"],
                opp_hand=det["opp_hand"],
                opp_active=det["opp_active"],
                deck_filler=det["deck"],
            )
            if begin_data.get("error") != 0:
                return self._fallback(state, legal_actions)

            root = MCTSNode(begin_data["state"])
            search_id = root.state.get("searchId", 0)
            root.untried_actions = [tuple(a) for a in legal_actions]
            errors = 0
            steps = 0

            for _ in range(self.iterations):
                if self._time_exhausted(start):
                    break
                value, path, step_error = self._run_iteration(root, player, start)
                steps += 1
                errors += int(step_error)
                if value is None:
                    value = self._evaluate_leaf(root.state["observation"], player)
                for node in path:
                    node.visit_count += 1
                    node.value_sum += value
                if steps > 0 and errors / steps > self.error_tolerance:
                    self.total_search_steps += steps
                    self.total_search_errors += errors
                    self.last_error_rate = errors / steps
                    return self._fallback(state, legal_actions)

            self.total_search_steps += steps
            self.total_search_errors += errors
            self.last_error_rate = errors / steps if steps else 0.0
            if not root.children:
                return self._fallback(state, legal_actions)

            best = max(root.children.values(), key=lambda n: (n.visit_count, n.value_sum))
            return list(best.action)
        except Exception:
            return self._fallback(state, legal_actions)
        finally:
            self.search_api.search_end(self.agent_ptr, search_id)

    def _determinize(self, state: dict, player: int) -> dict:
        """Sample hidden hand/deck/prize arrays for SearchBegin."""
        deck = _load_deck()
        current = state["current"]
        opponent = 1 - player
        players = current["players"]

        def sample_for(index):
            pstate = players[index]
            unseen = collections.Counter(deck)
            for cid in self.search_api.visible_card_ids(state, index):
                unseen[cid] -= 1
            pool = [cid for cid, count in unseen.items() for _ in range(max(0, count))]
            prize_count = len(pstate.get("prize") or [])
            hand_count = _hand_count(pstate)
            deck_count = int(pstate.get("deckCount") or max(0, len(pool) - prize_count - hand_count))
            needed = min(len(pool), prize_count + hand_count + deck_count)
            sampled = self.rng.sample(pool, needed) if needed else []
            prize = sampled[:prize_count]
            hand = sampled[prize_count:prize_count + hand_count]
            deck_cards = sampled[prize_count + hand_count:]
            if len(deck_cards) < deck_count:
                used = collections.Counter(prize + hand + deck_cards)
                rest = []
                for cid in pool:
                    if used[cid] > 0:
                        used[cid] -= 1
                    else:
                        rest.append(cid)
                deck_cards.extend(rest[: deck_count - len(deck_cards)])
            self.rng.shuffle(deck_cards)
            return deck_cards[:deck_count], prize, hand

        your_deck, your_prize, _your_hand = sample_for(player)
        opp_deck, opp_prize, opp_hand = sample_for(opponent)
        opp_active = self.search_api.card_ids(players[opponent].get("active"))
        return {
            "deck": deck,
            "your_deck": your_deck,
            "your_prize": your_prize,
            "opp_deck": opp_deck,
            "opp_prize": opp_prize,
            "opp_hand": opp_hand,
            "opp_active": opp_active,
        }

    def _uct_score(self, node: MCTSNode, parent_visits: int) -> float:
        if node.visit_count == 0:
            return float("inf")
        exploitation = node.value_sum / node.visit_count
        exploration = self.c_puct * math.sqrt(math.log(max(parent_visits, 1)) / node.visit_count)
        return exploitation + exploration

    def _evaluate_leaf(self, state: dict, player: int) -> float:
        try:
            current = state.get("current") or {}
            result = current.get("result", -1)
            if result >= 0:
                if result == player:
                    return 1.0
                if result == 2:
                    return 0.5
                return 0.0

            features = self.features_fn(state, player)
            keys = getattr(self.value_net, "feature_keys", list(features.keys()))
            values = [float(features.get(k, 0.0)) for k in keys]
            x = torch.tensor(values, dtype=torch.float32)
            mean = getattr(self.value_net, "feature_mean", None)
            std = getattr(self.value_net, "feature_std", None)
            if mean is not None and std is not None:
                x = (x - mean) / std
            with torch.no_grad():
                return float(self.value_net(x.unsqueeze(0)).item())
        except Exception:
            return _greedy_static_eval(state, player)

    def _run_iteration(self, root, player, start):
        node = root
        path = [node]

        while not node.is_terminal:
            if self._time_exhausted(start):
                return self._evaluate_leaf(node.state["observation"], player), path, False
            obs = node.state["observation"]
            select = obs.get("select")
            if not select or not select.get("option"):
                return self._evaluate_leaf(obs, player), path, False
            if node.untried_actions is None:
                node.untried_actions = [tuple(a) for a in _legal_actions(select, self.rng)]

            if node.untried_actions:
                action = node.untried_actions.pop(0)
                step_data, _ = self.search_api.search_step(
                    self.agent_ptr,
                    node.state.get("searchId", 0),
                    list(action),
                    select=select,
                )
                if step_data.get("error") != 0:
                    return self._evaluate_leaf(obs, player), path, True
                child = MCTSNode(step_data["state"], parent=node, action=action)
                node.children[action] = child
                path.append(child)
                return self._evaluate_leaf(child.state["observation"], player), path, False

            if not node.children:
                return self._evaluate_leaf(obs, player), path, False

            acting = obs.get("current", {}).get("yourIndex", player)
            if acting == player:
                node = max(node.children.values(), key=lambda child: self._uct_score(child, node.visit_count))
            else:
                node = min(
                    node.children.values(),
                    key=lambda child: (
                        child.value_sum / child.visit_count if child.visit_count else float("-inf")
                    ),
                )
            path.append(node)

        return self._evaluate_leaf(node.state["observation"], player), path, False

    def _time_exhausted(self, start):
        if self.time_limit_ms is None:
            return False
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return elapsed_ms >= self.time_limit_ms * 0.95

    def _fallback(self, state, legal_actions):
        self.fallback_decisions += 1
        self.last_used_fallback = True
        try:
            action = tuple(greedy.agent(state, None))
            legal = {tuple(a) for a in legal_actions}
            if action in legal:
                return list(action)
        except Exception:
            pass
        return list(legal_actions[0]) if legal_actions else []


def _load_deck():
    try:
        return greedy._load_deck(None)
    except Exception:
        from kaggle_environments.envs.cabt.cabt import deck as engine_deck

        return list(engine_deck)


def _hand_count(player_state):
    hand = player_state.get("hand")
    if isinstance(hand, list) and hand:
        return len(hand)
    return int(player_state.get("handCount") or 0)


def _legal_actions(select, rng=None, max_actions=24):
    options = select.get("option") or []
    n_options = len(options)
    min_count = select.get("minCount", 0)
    max_count = select.get("maxCount", 1)
    lo = min(max(min_count, 1 if n_options else 0), n_options)
    hi = min(max_count, n_options)
    if hi < lo or hi <= 0:
        return [[]]
    if hi == 1 and lo == 1:
        return [[i] for i in range(n_options)]

    actions = []
    for count in range(lo, hi + 1):
        try:
            combos = math.comb(n_options, count)
        except ValueError:
            combos = max_actions + 1
        if combos <= max_actions:
            actions.extend([list(c) for c in itertools.combinations(range(n_options), count)])
        else:
            rng = rng or random
            seen = set()
            while len(seen) < max_actions and len(actions) < max_actions:
                seen.add(tuple(sorted(rng.sample(range(n_options), count))))
            actions.extend([list(c) for c in seen])
    return actions or [[]]


def _is_terminal_state(search_state):
    obs = (search_state or {}).get("observation") or {}
    return (obs.get("current") or {}).get("result", -1) >= 0


def _greedy_static_eval(state, player):
    current = state.get("current") or {}
    players = current.get("players") or []
    if len(players) < 2:
        return 0.5
    result = current.get("result", -1)
    if result >= 0:
        return 1.0 if result == player else (0.5 if result == 2 else 0.0)
    me = players[player]
    opp = players[1 - player]
    my_prize = len(me.get("prize") or [])
    opp_prize = len(opp.get("prize") or [])
    return max(0.0, min(1.0, 0.5 + (opp_prize - my_prize) / 12.0))


def legal_actions_from_state(state):
    return _legal_actions(state.get("select") or {}, random)
