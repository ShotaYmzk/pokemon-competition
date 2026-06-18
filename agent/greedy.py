import os
import sys
import json
import random

_deck = None
_cards = None
_attacks = None


def _deck_supported_by_engine(deck):
    try:
        import ctypes
        import json as _json

        from kaggle_environments.envs.cabt.cg.sim import lib

        lib.AllCard.restype = ctypes.c_char_p
        card_ids = {c["cardId"] for c in _json.loads(lib.AllCard().decode())}
        return all(cid in card_ids for cid in deck)
    except Exception:
        return True


def _fallback_engine_deck():
    try:
        from kaggle_environments.envs.cabt.cabt import deck as engine_deck

        return list(engine_deck)
    except Exception:
        return None


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
            if not _deck_supported_by_engine(_deck):
                fallback = _fallback_engine_deck()
                if fallback is not None:
                    _deck = fallback
            return _deck
    raise FileNotFoundError(f"deck.csv not found in: {candidates}")


def _json_candidates(filename, config=None):
    candidates = []

    raw_path = None
    if config is not None:
        try:
            raw_path = config.get("__raw_path__")
        except AttributeError:
            raw_path = getattr(config, "__raw_path__", None)
    if raw_path:
        base = os.path.dirname(os.path.abspath(raw_path))
        candidates.append(os.path.join(base, filename))
        candidates.append(os.path.join(base, "..", "explore", filename))

    if "__file__" in globals():
        base = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(base, filename))
        candidates.append(os.path.join(base, "..", "explore", filename))

    candidates.append(os.path.join(os.getcwd(), filename))
    candidates.append(os.path.join(os.getcwd(), "explore", filename))
    candidates.append(os.path.join(os.getcwd(), "agent", filename))
    candidates.append("/kaggle_simulations/agent/" + filename)

    for p in sys.path:
        candidates.append(os.path.join(p, filename))
        candidates.append(os.path.join(p, "explore", filename))

    return candidates


def _load_json_lookup(filename, key, config=None):
    """Load a list of dicts from filename and index it by `key`. Returns {} if not found.

    Missing card/attack data degrades greedy logic gracefully to the random fallback
    rather than crashing, since the data files may not ship alongside the submission
    tarball in all environments.
    """
    seen = set()
    for path in _json_candidates(filename, config):
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


def _energy_counts(active_card):
    """Count energies attached to an active/bench card dict by energyType int."""
    counts = {}
    for e in active_card.get("energies", []) or []:
        counts[e] = counts.get(e, 0) + 1
    return counts


def _can_pay_cost(energy_counts, cost_energies):
    """Check whether attached energies (counts by type) can pay an attack cost.

    cost_energies is a list of energyType ints, where 0 means "any type" (colorless).
    This is a simplified, conservative check: count specific-type requirements first,
    then verify enough total energy remains (including spares) to cover colorless slots.
    """
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

    total_remaining = sum(remaining.values())
    return total_remaining >= colorless_needed


def _progress_toward_cost(energy_counts, cost_energies):
    """Heuristic: True if attaching one more energy would help meet cost_energies
    (i.e. the Pokemon doesn't already satisfy the cost and isn't grossly over-energized).
    """
    if _can_pay_cost(energy_counts, cost_energies):
        return False
    total_have = sum(energy_counts.values())
    return total_have < len(cost_energies)


def agent(obs, config=None):
    cards = _load_cards(config)
    attacks = _load_attacks(config)

    # Deck selection phase: obs["select"] is None
    if obs["select"] is None:
        return _load_deck(config)

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

    # Only apply greedy single-pick logic on the main action-menu select (type=0,
    # one action chosen at a time: attack=type7, play-card=type8, pass=type14).
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

    # Gather attack options (type=7) with resolved damage, keyed by option index.
    attack_choices = []  # (option_idx, damage, attack_dict)
    energy_attach_choices = []  # (option_idx, target_is_active)
    prize_taking_choices = []  # (option_idx,) - heuristic: type 8 attach when lethal not available
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
            # Playing a card from hand into play (energy attach if it's an Energy card).
            hand = me.get("hand") or []
            hidx = opt.get("index")
            if hidx is not None and hidx < len(hand):
                hand_card_id = hand[hidx].get("id")
                hand_card = cards.get(hand_card_id)
                if hand_card and hand_card.get("cardType") == 5:
                    target_active = opt.get("inPlayArea") == 4
                    energy_attach_choices.append((i, target_active, hand_card))
        elif otype == 14:
            pass_idx = i

    # 1) Lethal attack on opponent active.
    lethal = [c for c in attack_choices if c[1] >= opp_hp and opp_hp > 0]
    if lethal:
        best = max(lethal, key=lambda c: c[1])
        return [best[0]]

    # 2) Else max-damage attack vs opponent active HP.
    if attack_choices:
        best = max(attack_choices, key=lambda c: c[1])
        if best[1] > 0:
            return [best[0]]

    # 3) Else energy attachment progressing toward an attack's cost.
    if energy_attach_choices and my_attack_ids:
        target_atk_energies = []
        for aid in my_attack_ids:
            atk = attacks.get(aid)
            if atk:
                target_atk_energies.append(atk.get("energies", []))

        def helps_progress(choice):
            _, target_active, energy_card = choice
            if not target_active:
                return False
            etype = energy_card.get("energyType", 0)
            simulated = dict(my_energy_counts)
            simulated[etype] = simulated.get(etype, 0) + 1
            return any(_progress_toward_cost(my_energy_counts, cost) and
                       _can_pay_cost(simulated, cost) for cost in target_atk_energies) or \
                   any(_progress_toward_cost(my_energy_counts, cost) for cost in target_atk_energies)

        progressing = [c for c in energy_attach_choices if helps_progress(c)]
        if progressing:
            return [progressing[0][0]]
        # Any energy attach to active is still generically useful progress.
        active_attach = [c for c in energy_attach_choices if c[1]]
        if active_attach:
            return [active_attach[0][0]]

    # 4) Else option that takes a prize: approximate as "any attack that deals damage",
    # already covered above; if no attacks are payable, look for any type=8 play that
    # puts a Pokemon into the active slot (could set up a future KO) before passing.
    play_active_choices = [
        i for i, opt in enumerate(options)
        if opt.get("type") == 8 and opt.get("inPlayArea") == 4
    ]
    if play_active_choices:
        return [play_active_choices[0]]

    # 5) Else uniform random fallback (excluding nothing in particular).
    return fallback()
