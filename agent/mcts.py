"""Decentralized-determinization MCTS v0 for the cabt (Pokemon TCG) environment.

Design (see findings.md STEP 9 / task spec):
  - At every real decision point, sample ONE legal determinization of hidden
    information (T1-hardened: stadium/looking zones and face-down active
    Pokemon are accounted for) and SearchBegin fresh.
  - Run UCT simulations: select existing tree nodes via UCT, expand exactly
    one new SearchStep edge per simulation, evaluate the resulting state with
    a hand-crafted heuristic (NOT a rollout to terminal), backpropagate.
  - If a SearchStep call returns a nonzero error, treat that branch as a dead
    end: evaluate the last good state and back up the value (never crash).
  - If the root SearchBegin itself fails, or no legal action can be produced,
    fall back to a greedy heuristic over the real (non-search) obs -- this
    guarantees MCTS is never worse than the greedy anchor by construction.

This file is intentionally self-contained (no imports from sibling agent/*.py
or explore/*.py) because Kaggle's submission tarball ships agent/ as a flat,
non-package directory executed via exec(); cross-file imports between
sibling scripts are not reliable under that execution model.
"""
import collections
import ctypes
import itertools
import json
import math
import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# Data loading (deck.csv / all_cards.json / all_attacks.json) -- same
# multi-candidate-path search pattern as agent/greedy.py, duplicated here
# because sibling imports aren't reliable under Kaggle's exec() model.
# ---------------------------------------------------------------------------

_deck = None
_cards = None
_attacks = None


def _candidates(filename, config=None):
    candidates = []
    raw_path = None
    if config is not None:
        try:
            raw_path = config.get("__raw_path__")
        except AttributeError:
            raw_path = getattr(config, "__raw_path__", None)
    if raw_path:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(raw_path)), filename))
    if "__file__" in globals():
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    candidates.append(os.path.join(os.getcwd(), filename))
    candidates.append(os.path.join(os.getcwd(), "agent", filename))
    candidates.append("/kaggle_simulations/agent/" + filename)
    for p in sys.path:
        candidates.append(os.path.join(p, filename))
    return candidates


def _load_deck(config=None):
    global _deck
    if _deck is not None:
        return _deck
    seen = set()
    for path in _candidates("deck.csv", config):
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            with open(path) as f:
                _deck = [int(line.strip()) for line in f if line.strip()]
            assert len(_deck) == 60, f"deck.csv must have 60 cards, got {len(_deck)}"
            return _deck
    raise FileNotFoundError("deck.csv not found")


def _load_json_lookup(filename, key, config=None):
    seen = set()
    for path in _candidates(filename, config):
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    items = json.load(f)
                return {item[key]: item for item in items}
            except Exception:
                continue
    return {}


def _load_cards(config=None):
    global _cards
    if _cards is None:
        _cards = _load_json_lookup("all_cards.json", "cardId", config)
    return _cards


def _load_attacks(config=None):
    global _attacks
    if _attacks is None:
        _attacks = _load_json_lookup("all_attacks.json", "attackId", config)
    return _attacks


# ---------------------------------------------------------------------------
# ctypes wiring for SearchBegin/SearchStep/SearchEnd/SearchRelease.
#
# IMPORTANT: search_id is int64 in the real C signature and SearchRelease
# takes TWO args (agent_ptr, search_id). An earlier exploratory version of
# this binding (explore/search_api.py, pre-fix) declared search_id as a
# 32-bit c_int and called SearchRelease with only ONE argument -- an
# under-specified C call whose missing search_id register held leftover
# garbage, corrupting the engine's internal search-state table. That bug is
# the prime suspect behind the irreproducible error=5 failures recorded in
# findings.md STEP 7/8, and is fixed here from the start (verified against
# the official reference binding in
# pokemon-tcg-ai-battle/sample_submission/cg/sim.py).
# ---------------------------------------------------------------------------

IntPtr = ctypes.POINTER(ctypes.c_int)
_TYPES_BOUND = False
_lib = None
_shared_agent_ptr = None


def _get_lib():
    global _lib
    if _lib is not None:
        return _lib
    from kaggle_environments.envs.cabt.cg.sim import lib
    _lib = lib
    return _lib


def _bind_types():
    global _TYPES_BOUND
    if _TYPES_BOUND:
        return
    lib = _get_lib()

    lib.AgentStart.restype = ctypes.c_void_p
    lib.AgentStart.argtypes = []

    lib.SearchBegin.restype = ctypes.c_char_p
    lib.SearchBegin.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
        IntPtr, IntPtr, IntPtr, IntPtr, IntPtr, IntPtr, ctypes.c_int,
    ]

    lib.SearchStep.restype = ctypes.c_char_p
    lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int64, IntPtr, ctypes.c_int]

    lib.SearchEnd.restype = None
    lib.SearchEnd.argtypes = [ctypes.c_void_p]

    if hasattr(lib, "SearchRelease"):
        lib.SearchRelease.restype = None
        lib.SearchRelease.argtypes = [ctypes.c_void_p, ctypes.c_int64]

    _TYPES_BOUND = True


def agent_start():
    _bind_types()
    return _get_lib().AgentStart()


def get_shared_agent_ptr():
    """libcg.so exports no AgentEnd/AgentRelease symbol -- AgentStart() is
    meant to be called ONCE and its memory reused across many search_begin/
    search_step/search_end cycles (SearchEnd's docstring: "Memory used during
    the search will be reused in the next search"; the official reference
    api.py also caches a single module-level agent_ptr). Calling agent_start()
    fresh per simulation (the original version of this file) leaks ~tens of
    MB per call with no way to free it, ballooning to multi-GB RSS within a
    single game and getting OOM-killed -- confirmed empirically. Always use
    this shared pointer instead of agent_start() inside the MCTS loop."""
    global _shared_agent_ptr
    if _shared_agent_ptr is None:
        _shared_agent_ptr = agent_start()
    return _shared_agent_ptr


def _make_int_array(values, min_len=64, filler=None):
    vals = list(values)
    fill = list(filler or [1])
    while len(vals) < min_len:
        vals.append(fill[len(vals) % len(fill)])
    return (ctypes.c_int * len(vals))(*vals)


def card_ids(cards):
    ids = []
    for card in cards or []:
        if isinstance(card, dict):
            cid = card.get("id", card.get("cardId"))
            if isinstance(cid, int):
                ids.append(cid)
    return ids


def visible_card_ids(obs, player_index):
    """Known card IDs visible for a player: hand/active/bench/discard, nested
    preEvolution/energyCards/tools on active/bench, AND the global
    stadium/looking zones filtered by playerIndex (T1 fix: these are NOT
    per-player PlayerState fields, and omitting them silently undercounts a
    player's true card total by exactly the number of cards they have there;
    confirmed empirically against a played Stadium card -- see findings.md
    STEP 9)."""
    player = obs["current"]["players"][player_index]
    ids = []
    for zone in ("hand", "active", "bench", "discard"):
        ids.extend(card_ids(player.get(zone)))
    for zone in ("active", "bench"):
        for card in player.get(zone) or []:
            if isinstance(card, dict):
                ids.extend(card_ids(card.get("preEvolution")))
                ids.extend(card_ids(card.get("energyCards")))
                ids.extend(card_ids(card.get("tools")))
    for zone in ("stadium", "looking"):
        for card in obs["current"].get(zone) or []:
            if isinstance(card, dict) and card.get("playerIndex") == player_index:
                cid = card.get("id", card.get("cardId"))
                if isinstance(cid, int):
                    ids.append(cid)
    return ids


def _parse(raw):
    text = raw.decode() if raw else ""
    try:
        data = json.loads(text) if text else {"error": "empty"}
    except json.JSONDecodeError:
        data = {"state": None, "error": "json"}
    return data, text


def search_begin(agent_ptr, sbi_bytes, your_deck, your_prize, opp_deck, opp_prize,
                  opp_hand, opp_active, manual_coin=0, deck_filler=None):
    _bind_types()
    arrays = [your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active]
    holders = [_make_int_array(a, filler=deck_filler) for a in arrays]
    raw = _get_lib().SearchBegin(agent_ptr, sbi_bytes, len(sbi_bytes), *holders, manual_coin)
    return _parse(raw)


def _search_step_raw(agent_ptr, search_id, action):
    _bind_types()
    action = list(action)
    arr = _make_int_array(action, min_len=max(1, len(action)), filler=action or [0])
    raw = _get_lib().SearchStep(agent_ptr, search_id, arr, len(action))
    return _parse(raw)


def search_step(agent_ptr, search_id, action, select=None):
    """Single call for single-select; sequential 1-at-a-time calls for
    multi-select (minCount/maxCount > 1) -- see findings.md STEP 8."""
    is_multi = bool(select) and (
        select.get("maxCount", 1) > 1 or select.get("minCount", 0) > 1
    )
    if not is_multi or len(action) <= 1:
        return _search_step_raw(agent_ptr, search_id, action)
    parsed, raw = None, None
    for idx in action:
        parsed, raw = _search_step_raw(agent_ptr, search_id, [idx])
        if parsed.get("error") != 0:
            return parsed, raw
    return parsed, raw


def search_end(agent_ptr, search_id=0):
    _bind_types()
    lib = _get_lib()
    lib.SearchEnd(agent_ptr)
    if hasattr(lib, "SearchRelease"):
        lib.SearchRelease(agent_ptr, search_id)


# ---------------------------------------------------------------------------
# Determinization (T1-hardened): see findings.md STEP 9 for the two bugs
# found and fixed (stadium/looking zone undercounting, missing face-down
# active-Pokemon guess).
# ---------------------------------------------------------------------------

_pokemon_ids_cache = None


def _pokemon_card_ids(deck, cards):
    global _pokemon_ids_cache
    if _pokemon_ids_cache is None:
        _pokemon_ids_cache = {cid for cid in deck if cards.get(cid, {}).get("cardType") == 0}
    return _pokemon_ids_cache


def sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng, cards):
    """Build a legal determinization of hidden information. Raises ValueError
    if the pool is too small (should not happen with a correct deck/visible
    accounting); callers should treat that as "fall back to greedy"."""
    your_player = obs["current"]["players"][your_index]
    opp_player = obs["current"]["players"][opp_index]

    your_visible = visible_card_ids(obs, your_index)
    opp_visible = visible_card_ids(obs, opp_index)

    your_unseen = collections.Counter(deck)
    for cid in your_visible:
        your_unseen[cid] -= 1
    your_unseen_pool = [cid for cid, n in your_unseen.items() for _ in range(max(n, 0))]

    your_prize_count = len(your_player["prize"])
    if your_prize_count > len(your_unseen_pool):
        raise ValueError("not enough unseen cards for your_prize")
    your_prize_sample = rng.sample(your_unseen_pool, your_prize_count)

    your_deck_removed = collections.Counter(your_unseen_pool)
    for cid in your_prize_sample:
        your_deck_removed[cid] -= 1
    your_deck_sample = []
    for cid in deck:
        if your_deck_removed[cid] > 0:
            your_deck_sample.append(cid)
            your_deck_removed[cid] -= 1
    your_deck_sample = your_deck_sample[: your_player["deckCount"]]

    opp_active_raw = opp_player.get("active") or []
    opp_active_facedown = len(opp_active_raw) > 0 and opp_active_raw[0] is None

    opp_unseen = collections.Counter(deck)
    for cid in opp_visible:
        opp_unseen[cid] -= 1
    opp_unseen_pool = [cid for cid, n in opp_unseen.items() for _ in range(max(n, 0))]

    opp_active_sample = []
    if opp_active_facedown:
        pokemon_ids = _pokemon_card_ids(deck, cards)
        candidates = [cid for cid in opp_unseen_pool if cid in pokemon_ids]
        if not candidates:
            raise ValueError("no Pokemon candidates to guess face-down active")
        guess = rng.choice(candidates)
        opp_active_sample = [guess]
        opp_unseen_pool.remove(guess)

    opp_prize_count = len(opp_player["prize"])
    opp_hand_count = opp_player["handCount"]
    opp_deck_count = opp_player["deckCount"]
    needed = opp_prize_count + opp_hand_count + opp_deck_count
    if needed > len(opp_unseen_pool):
        raise ValueError("not enough unseen cards for opponent zones")

    sampled = rng.sample(opp_unseen_pool, needed)
    opp_prize_sample = sampled[:opp_prize_count]
    opp_hand_sample = sampled[opp_prize_count: opp_prize_count + opp_hand_count]
    opp_deck_sample = sampled[opp_prize_count + opp_hand_count:]

    # Shuffle deck-order arrays: T0-2 found SearchBegin's draws are
    # order-sensitive, and the true order is unknowable, so we randomize it
    # per determinization (root-sampling IS-MCTS style) rather than pretend
    # any particular order is "correct".
    your_deck_sample = list(your_deck_sample)
    opp_deck_sample = list(opp_deck_sample)
    rng.shuffle(your_deck_sample)
    rng.shuffle(opp_deck_sample)

    return {
        "your_deck": your_deck_sample,
        "your_prize": your_prize_sample,
        "opp_deck": opp_deck_sample,
        "opp_prize": opp_prize_sample,
        "opp_hand": opp_hand_sample,
        "opp_active": opp_active_sample if opp_active_facedown else card_ids(opp_player.get("active")),
    }


# ---------------------------------------------------------------------------
# Heuristic leaf evaluation (greedy-derived). Primary term: prize
# differential (dominant signal for who is winning). Secondary terms: damage
# potential against the opponent's active relative to its HP, threat from
# the opponent's active against my HP, and bench development.
# ---------------------------------------------------------------------------

def _energy_counts(active_card):
    counts = {}
    for e in active_card.get("energies", []) or []:
        counts[e] = counts.get(e, 0) + 1
    return counts


def _can_pay_cost(energy_counts, cost_energies):
    needed_specific = {}
    colorless_needed = 0
    for e in cost_energies:
        if e == 0:
            colorless_needed += 1
        else:
            needed_specific[e] = needed_specific.get(e, 0) + 1
    remaining = dict(energy_counts)
    for etype, n in needed_specific.items():
        have = remaining.get(etype, 0)
        if have < n:
            return False
        remaining[etype] = have - n
    return sum(remaining.values()) >= colorless_needed


def _best_attack_damage(active_card, cards, attacks):
    card = cards.get(active_card.get("id"))
    if not card:
        return 0
    energy_counts = _energy_counts(active_card)
    best = 0
    for aid in card.get("attacks", []):
        atk = attacks.get(aid)
        if atk and _can_pay_cost(energy_counts, atk.get("energies", [])):
            best = max(best, atk.get("damage", 0))
    return best


def evaluate_state(obs, your_index, cards, attacks):
    """Scalar evaluation in [-1, 1] from your_index's perspective."""
    cur = obs["current"]
    opp_index = 1 - your_index
    result = cur.get("result", -1)
    if result == your_index:
        return 1.0
    if result == opp_index:
        return -1.0
    if result == 2:
        return 0.0

    me = cur["players"][your_index]
    opp = cur["players"][opp_index]

    # Prize differential dominates: fewer remaining prizes for me (I've KO'd
    # more of the opponent's Pokemon) means I'm closer to winning.
    my_prize = len(me["prize"])
    opp_prize = len(opp["prize"])
    prize_term = (opp_prize - my_prize) / 6.0

    dmg_term = 0.0
    threat_term = 0.0
    my_active_list = me.get("active") or []
    opp_active_list = opp.get("active") or []
    if my_active_list and my_active_list[0] and opp_active_list and opp_active_list[0]:
        my_active, opp_active = my_active_list[0], opp_active_list[0]
        opp_hp = max(opp_active.get("hp", 0) or 0, 1)
        my_hp = max(my_active.get("hp", 0) or 0, 1)
        dmg_term = min(_best_attack_damage(my_active, cards, attacks) / opp_hp, 1.0)
        threat_term = -min(_best_attack_damage(opp_active, cards, attacks) / my_hp, 1.0)

    board_term = (len(me.get("bench") or []) - len(opp.get("bench") or [])) / 5.0

    score = 0.6 * prize_term + 0.2 * dmg_term + 0.1 * threat_term + 0.1 * board_term
    return max(-1.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Greedy fallback / anchor policy, operating directly on the real (non-
# search) obs. MCTS falls back to this whenever the search chain can't be
# used at all (root SearchBegin failure, empty hidden-info pool, etc.), so
# MCTS is guaranteed to never be worse than this anchor.
# ---------------------------------------------------------------------------

def greedy_action(obs, cards, attacks):
    select = obs["select"]
    options = select["option"]
    max_count = select["maxCount"]
    min_count = select.get("minCount", 0)
    n_options = len(options)

    def fallback():
        count = min(max(min_count, 1 if n_options else 0), max_count, n_options)
        if count <= 0:
            return []
        return random.sample(list(range(n_options)), count)

    if select.get("type") != 0 or max_count != 1 or not cards or not attacks:
        return fallback()

    current = obs.get("current") or {}
    players = current.get("players")
    your_index = current.get("yourIndex")
    if not players or your_index is None:
        return fallback()

    me = players[your_index]
    opp = players[1 - your_index]
    my_active_list = me.get("active") or []
    opp_active_list = opp.get("active") or []
    if not my_active_list or not opp_active_list:
        return fallback()

    my_active = my_active_list[0]
    opp_active = opp_active_list[0]
    opp_hp = opp_active.get("hp", 0)
    my_energy_counts = _energy_counts(my_active)
    my_card = cards.get(my_active.get("id"))
    my_attack_ids = my_card.get("attacks", []) if my_card else []

    attack_choices = []
    energy_attach_choices = []
    pass_idx = None
    for i, opt in enumerate(options):
        otype = opt.get("type")
        if otype == 7:
            atk_idx = opt.get("index", 0)
            if atk_idx < len(my_attack_ids):
                atk = attacks.get(my_attack_ids[atk_idx])
                if atk and _can_pay_cost(my_energy_counts, atk.get("energies", [])):
                    attack_choices.append((i, atk.get("damage", 0), atk))
        elif otype == 8:
            hand = me.get("hand") or []
            hidx = opt.get("index")
            if hidx is not None and hidx < len(hand):
                hand_card = cards.get(hand[hidx].get("id"))
                if hand_card and hand_card.get("cardType") == 5:
                    target_active = opt.get("inPlayArea") == 4
                    energy_attach_choices.append((i, target_active, hand_card))
        elif otype == 14:
            pass_idx = i

    lethal = [c for c in attack_choices if c[1] >= opp_hp and opp_hp > 0]
    if lethal:
        return [max(lethal, key=lambda c: c[1])[0]]

    if attack_choices:
        best = max(attack_choices, key=lambda c: c[1])
        if best[1] > 0:
            return [best[0]]

    if energy_attach_choices and my_attack_ids:
        target_atk_energies = [attacks[aid].get("energies", []) for aid in my_attack_ids if aid in attacks]

        def helps(choice):
            _, target_active, energy_card = choice
            if not target_active:
                return False
            simulated = dict(my_energy_counts)
            etype = energy_card.get("energyType", 0)
            simulated[etype] = simulated.get(etype, 0) + 1
            return any(_can_pay_cost(simulated, cost) and not _can_pay_cost(my_energy_counts, cost)
                       for cost in target_atk_energies)

        progressing = [c for c in energy_attach_choices if helps(c)]
        if progressing:
            return [progressing[0][0]]
        active_attach = [c for c in energy_attach_choices if c[1]]
        if active_attach:
            return [active_attach[0][0]]

    play_active = [i for i, opt in enumerate(options) if opt.get("type") == 8 and opt.get("inPlayArea") == 4]
    if play_active:
        return [play_active[0]]

    return fallback()


# ---------------------------------------------------------------------------
# Action enumeration for a SelectData dict: single-select -> one action per
# option; multi-select -> capped combination sampling (avoids combinatorial
# blow-up for "discard N of M" effects with large M).
# ---------------------------------------------------------------------------

def enumerate_actions(sel, rng, max_actions=12):
    opts = sel.get("option", [])
    n = len(opts)
    mc = min(sel.get("maxCount", 1), n)
    mc = max(mc, sel.get("minCount", 0))
    mc = min(mc, n)
    if mc <= 0:
        return [[]]
    if mc == 1:
        return [[i] for i in range(n)]
    try:
        total_combos = math.comb(n, mc)
    except ValueError:
        total_combos = 0
    if 0 < total_combos <= max_actions:
        return [list(c) for c in itertools.combinations(range(n), mc)]
    seen = set()
    actions = []
    tries = 0
    while len(actions) < max_actions and tries < max_actions * 20:
        tries += 1
        combo = tuple(sorted(rng.sample(range(n), mc)))
        if combo in seen:
            continue
        seen.add(combo)
        actions.append(list(combo))
    return actions


# ---------------------------------------------------------------------------
# MCTS tree + UCT.
# ---------------------------------------------------------------------------

class MCTSNode:
    __slots__ = ("parent", "children", "N", "W", "untried")

    def __init__(self, parent):
        self.parent = parent
        self.children = {}  # action tuple -> MCTSNode
        self.N = 0
        self.W = 0.0
        self.untried = None  # list of not-yet-tried actions; set on first visit


def _uct_pick(node, c_uct, sign):
    """sign=+1 when it's the root player's decision at this node (maximize our
    value, standard UCT); sign=-1 when it's the opponent's decision being
    modeled within the search chain (the opponent picks to MINIMIZE our
    value, i.e. they maximize -value -- negamax-style). Without this sign
    flip, every node in the tree -- including the opponent's own choices --
    gets selected to maximize OUR value, which models the opponent as an ally
    instead of an adversary. Confirmed empirically: this bug alone made MCTS
    lose to a uniform-random opponent (40% win rate) before the fix."""
    best_key, best_child, best_score = None, None, -1e18
    for key, child in node.children.items():
        if child.N == 0:
            score = float("inf")
        else:
            score = sign * (child.W / child.N) + c_uct * math.sqrt(math.log(max(node.N, 1)) / child.N)
        if score > best_score:
            best_score, best_key, best_child = score, key, child
    return best_key, best_child


def run_mcts(sbi_bytes, det_arrays, deck, your_index, cards, attacks, rng,
             max_sims=200, max_seconds=1.5, max_depth=30, c_uct=1.4):
    """Run UCT simulations from a fixed determinization. Returns
    (best_action, error_truncations, n_sims_run) where best_action is the
    most-visited root child's action (list of option indices), or None if no
    simulation ever succeeded (caller should fall back to greedy)."""
    root = MCTSNode(parent=None)
    t_start = time.perf_counter()
    n_sims = 0
    n_truncated = 0
    ap = get_shared_agent_ptr()

    while n_sims < max_sims and (time.perf_counter() - t_start) < max_seconds:
        n_sims += 1
        begin_data, _ = search_begin(
            ap, sbi_bytes,
            your_deck=det_arrays["your_deck"], your_prize=det_arrays["your_prize"],
            opp_deck=det_arrays["opp_deck"], opp_prize=det_arrays["opp_prize"],
            opp_hand=det_arrays["opp_hand"], opp_active=det_arrays["opp_active"],
            deck_filler=deck,
        )
        if begin_data.get("error") != 0:
            search_end(ap)
            n_truncated += 1
            continue

        cur_state = begin_data["state"]
        node = root
        path = [node]
        depth = 0
        value = None

        while True:
            obs = cur_state["observation"]
            result = obs["current"].get("result", -1)
            if result >= 0:
                value = 1.0 if result == your_index else (-1.0 if result != 2 else 0.0)
                break
            sel = obs.get("select")
            if not sel or not sel.get("option"):
                value = evaluate_state(obs, your_index, cards, attacks)
                break
            if depth >= max_depth:
                value = evaluate_state(obs, your_index, cards, attacks)
                break

            if node.untried is None:
                node.untried = enumerate_actions(sel, rng)

            # Whose decision is this select for? The chain presents BOTH
            # players' decisions (obs['current']['yourIndex'] flips to
            # whoever is on-move), so the sign of the UCT exploitation term
            # must flip when it's the opponent's turn within the simulation
            # -- see _uct_pick docstring.
            acting_index = obs["current"].get("yourIndex", your_index)
            sign = 1.0 if acting_index == your_index else -1.0

            expanding = bool(node.untried)
            if expanding:
                action = node.untried.pop(rng.randrange(len(node.untried)))
            else:
                if not node.children:
                    value = evaluate_state(obs, your_index, cards, attacks)
                    break
                _, child_for_selection = _uct_pick(node, c_uct, sign)
                action = None
                for key, child in node.children.items():
                    if child is child_for_selection:
                        action = list(key)
                        break

            step_data, _ = search_step(ap, 0, action, select=sel)
            depth += 1
            if step_data.get("error") != 0:
                # Truncate: evaluate at the last good state, don't crash.
                value = evaluate_state(obs, your_index, cards, attacks)
                n_truncated += 1
                break

            cur_state = step_data["state"]
            key = tuple(action)
            child = node.children.get(key)
            if child is None:
                child = MCTSNode(parent=node)
                node.children[key] = child
            path.append(child)
            node = child

            if expanding:
                obs2 = cur_state["observation"]
                result2 = obs2["current"].get("result", -1)
                if result2 >= 0:
                    value = 1.0 if result2 == your_index else (-1.0 if result2 != 2 else 0.0)
                else:
                    value = evaluate_state(obs2, your_index, cards, attacks)
                break

        search_end(ap)
        for n in path:
            n.N += 1
            n.W += value

    if not root.children:
        return None, n_truncated, n_sims

    best_key = max(root.children, key=lambda k: root.children[k].N)
    return list(best_key), n_truncated, n_sims


# ---------------------------------------------------------------------------
# Top-level agent entry point.
# ---------------------------------------------------------------------------

def agent(obs, config=None):
    cards = _load_cards(config)
    attacks = _load_attacks(config)

    if obs["select"] is None:
        return _load_deck(config)

    select = obs["select"]
    if not select.get("option"):
        return []

    sbi = obs.get("search_begin_input")
    cur = obs.get("current")
    if not sbi or not cur:
        return greedy_action(obs, cards, attacks)

    your_index = cur["yourIndex"]
    opp_index = 1 - your_index
    deck = _load_deck(config)
    rng = random.Random()

    try:
        det_arrays = sample_determinized_hidden_state(obs, deck, your_index, opp_index, rng, cards)
    except ValueError:
        return greedy_action(obs, cards, attacks)

    sbi_bytes = sbi.encode("ascii")
    max_sims = int(config.get("mcts_max_sims", 300)) if config else 300
    max_seconds = float(config.get("mcts_seconds", 1.0)) if config else 1.0
    max_depth = int(config.get("mcts_max_depth", 30)) if config else 30

    best_action, _n_truncated, n_sims = run_mcts(
        sbi_bytes, det_arrays, deck, your_index, cards, attacks, rng,
        max_sims=max_sims, max_seconds=max_seconds, max_depth=max_depth,
    )

    if best_action is None or n_sims == 0:
        return greedy_action(obs, cards, attacks)

    return best_action
