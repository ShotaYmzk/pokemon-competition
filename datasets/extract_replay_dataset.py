"""Extract deck summaries and imitation-learning rows from replay JSON files."""

from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_REPLAY_GLOB = "datasets/top_replays/replays/*.json"
DEFAULT_CARD_CSV = Path("pokemon-tcg-ai-battle/JP_Card_Data.csv")
DEFAULT_OUT_DIR = Path("datasets/top_replays/extracted")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_card_names(path: Path) -> dict[int, str]:
    names: dict[int, str] = {}
    if not path.exists():
        return names
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            card_id = row.get("カード ID", "")
            if card_id.isdigit():
                names[int(card_id)] = row.get("カード名", "")
    return names


def episode_id_from_replay(path: Path, data: dict[str, Any]) -> int | str:
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    value = info.get("EpisodeId") or data.get("episode_id") or data.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    stem = path.stem
    if stem.isdigit():
        return int(stem)
    return stem


def team_names(data: dict[str, Any]) -> list[str | None]:
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    names = info.get("TeamNames")
    if isinstance(names, list):
        return [str(name) if name is not None else None for name in names]
    agents = info.get("Agents")
    if isinstance(agents, list):
        result: list[str | None] = []
        for agent in agents:
            if isinstance(agent, dict):
                name = agent.get("Name")
                result.append(str(name) if name is not None else None)
        return result
    return []


def is_int_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, int) for item in value)


def looks_like_deck_action(action: Any) -> bool:
    return is_int_list(action) and len(action) == 60


def is_valid_option_action(action: Any, option_count: int) -> bool:
    if not is_int_list(action):
        return False
    return all(0 <= item < option_count for item in action)


def compact_select(select: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": select.get("type"),
        "context": select.get("context"),
        "contextCard": select.get("contextCard"),
        "minCount": select.get("minCount"),
        "maxCount": select.get("maxCount"),
        "remainDamageCounter": select.get("remainDamageCounter"),
        "remainEnergyCost": select.get("remainEnergyCost"),
        "option": select.get("option"),
    }


def label_action(
    steps: list[Any],
    step_index: int,
    player_index: int,
    alignment: str,
    same_step_state: dict[str, Any],
) -> tuple[Any, int | None]:
    if alignment == "same-step":
        return same_step_state.get("action"), step_index

    action_step = step_index + 1
    if action_step >= len(steps):
        return None, None
    next_step = steps[action_step]
    if not isinstance(next_step, list) or player_index >= len(next_step):
        return None, None
    next_state = next_step[player_index]
    if not isinstance(next_state, dict):
        return None, None
    return next_state.get("action"), action_step


def deck_validation(deck: list[int], card_names: dict[int, str]) -> dict[str, Any]:
    counts = Counter(deck)
    unknown_ids = sorted(card_id for card_id in counts if card_id not in card_names)
    over_limit = {
        str(card_id): count
        for card_id, count in sorted(counts.items())
        if card_id not in range(1, 9) and count > 4
    }
    return {
        "valid_60": len(deck) == 60,
        "unknown_ids": unknown_ids,
        "over_limit": over_limit,
    }


def is_valid_select_action(action: Any, option_count: int, min_count: Any, max_count: Any) -> bool:
    if not is_valid_option_action(action, option_count):
        return False
    if isinstance(min_count, int) and len(action) < min_count:
        return False
    if isinstance(max_count, int) and len(action) > max_count:
        return False
    return True


def action_kind(action: Any, option_count: int, min_count: Any, max_count: Any) -> str:
    if action is None:
        return "missing"
    if not is_int_list(action):
        return "non_int_list"
    if len(action) == 0:
        return "empty_optional" if min_count == 0 else "empty_invalid"
    if is_valid_option_action(action, option_count):
        if is_valid_select_action(action, option_count, min_count, max_count):
            return "option_indices"
        return "count_invalid"
    return "invalid_option_indices"


def is_forced_select(select: dict[str, Any], option_count: int) -> bool:
    min_count = select.get("minCount")
    max_count = select.get("maxCount")
    if option_count <= 1 and min_count == max_count:
        return True
    return option_count == 1 and max_count == 1


def extract_replay(
    path: Path,
    card_names: dict[int, str],
    include_current: bool,
    label_alignment: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, dict):
        return [], [], [], {"path": str(path), "skipped": "top_level_not_dict"}

    steps = data.get("steps")
    if not isinstance(steps, list):
        return [], [], [], {"path": str(path), "skipped": "missing_steps"}

    episode_id = episode_id_from_replay(path, data)
    names = team_names(data)
    rewards = data.get("rewards") if isinstance(data.get("rewards"), list) else []
    statuses = data.get("statuses") if isinstance(data.get("statuses"), list) else []

    decks: dict[int, list[int]] = {}
    examples: list[dict[str, Any]] = []
    select_count = 0
    valid_action_count = 0
    invalid_action_count = 0
    deck_action_count = 0

    for step_index, step in enumerate(steps):
        if not isinstance(step, list):
            continue
        for player_index, agent_state in enumerate(step):
            if not isinstance(agent_state, dict):
                continue
            same_step_action = agent_state.get("action")
            if looks_like_deck_action(same_step_action):
                decks.setdefault(player_index, list(same_step_action))
                deck_action_count += 1

            obs = agent_state.get("observation")
            if not isinstance(obs, dict):
                continue
            select = obs.get("select")
            if not isinstance(select, dict):
                continue
            option = select.get("option")
            if not isinstance(option, list):
                continue

            select_count += 1
            action, action_step = label_action(
                steps,
                step_index,
                player_index,
                label_alignment,
                agent_state,
            )
            min_count = select.get("minCount")
            max_count = select.get("maxCount")
            valid_option_indices = is_valid_option_action(action, len(option))
            valid_action = is_valid_select_action(action, len(option), min_count, max_count)
            kind = action_kind(action, len(option), min_count, max_count)
            if valid_action:
                valid_action_count += 1
            else:
                invalid_action_count += 1

            row: dict[str, Any] = {
                "episode_id": episode_id,
                "source_path": str(path),
                "step": step_index,
                "action_step": action_step,
                "label_alignment": label_alignment,
                "player_index": player_index,
                "team_name": names[player_index] if player_index < len(names) else None,
                "reward": rewards[player_index] if player_index < len(rewards) else None,
                "status": statuses[player_index] if player_index < len(statuses) else None,
                "select_type": select.get("type"),
                "context": select.get("context"),
                "min_count": min_count,
                "max_count": max_count,
                "option_count": len(option),
                "action": action,
                "valid_option_indices": valid_option_indices,
                "valid_select_action": valid_action,
                "action_kind": kind,
                "is_forced": is_forced_select(select, len(option)),
                "select": compact_select(select),
            }
            if include_current:
                row["current"] = obs.get("current")
            examples.append(row)

    deck_rows: list[dict[str, Any]] = []
    deck_order_rows: list[dict[str, Any]] = []
    for player_index, deck in sorted(decks.items()):
        counts = Counter(deck)
        validation = deck_validation(deck, card_names)
        deck_order_rows.append(
            {
                "episode_id": episode_id,
                "source_path": str(path),
                "player_index": player_index,
                "team_name": names[player_index] if player_index < len(names) else None,
                "reward": rewards[player_index] if player_index < len(rewards) else None,
                "status": statuses[player_index] if player_index < len(statuses) else None,
                "deck_order": deck,
                "deck_counts": {str(card_id): count for card_id, count in sorted(counts.items())},
                **validation,
            }
        )
        for card_id, count in sorted(counts.items()):
            deck_rows.append(
                {
                    "episode_id": episode_id,
                    "source_path": str(path),
                    "player_index": player_index,
                    "team_name": names[player_index] if player_index < len(names) else None,
                    "reward": rewards[player_index] if player_index < len(rewards) else None,
                    "status": statuses[player_index] if player_index < len(statuses) else None,
                    "card_id": card_id,
                    "card_name": card_names.get(card_id, ""),
                    "count": count,
                }
            )

    summary = {
        "path": str(path),
        "episode_id": episode_id,
        "steps": len(steps),
        "deck_players": sorted(decks),
        "deck_action_count": deck_action_count,
        "select_count": select_count,
        "examples": len(examples),
        "valid_action_count": valid_action_count,
        "invalid_action_count": invalid_action_count,
    }
    return deck_rows, deck_order_rows, examples, summary


def write_deck_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "episode_id",
        "source_path",
        "player_index",
        "team_name",
        "reward",
        "status",
        "card_id",
        "card_name",
        "count",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_card_popularity_csv(path: Path, deck_rows: list[dict[str, Any]]) -> None:
    totals: Counter[int] = Counter()
    names: dict[int, str] = {}
    deck_presence: Counter[int] = Counter()
    seen_pairs: set[tuple[Any, Any, int]] = set()
    for row in deck_rows:
        card_id = int(row["card_id"])
        totals[card_id] += int(row["count"])
        names[card_id] = str(row.get("card_name") or "")
        key = (row["episode_id"], row["player_index"], card_id)
        if key not in seen_pairs:
            deck_presence[card_id] += 1
            seen_pairs.add(key)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["card_id", "card_name", "total_count", "deck_presence"],
        )
        writer.writeheader()
        for card_id, total in totals.most_common():
            writer.writerow(
                {
                    "card_id": card_id,
                    "card_name": names.get(card_id, ""),
                    "total_count": total,
                    "deck_presence": deck_presence[card_id],
                }
            )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def clear_output_files(out_dir: Path) -> None:
    for name in (
        "imitation_examples.jsonl",
        "deck_cards.csv",
        "deck_orders.jsonl",
        "card_popularity.csv",
        "summary.json",
    ):
        path = out_dir / name
        if path.exists():
            path.unlink()


def expand_replay_glob(pattern: str) -> list[Path]:
    return sorted(Path(match) for match in glob.glob(pattern))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-glob", default=DEFAULT_REPLAY_GLOB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--card-csv", type=Path, default=DEFAULT_CARD_CSV)
    parser.add_argument("--include-current", action="store_true")
    parser.add_argument(
        "--label-alignment",
        choices=["next-step", "same-step"],
        default="next-step",
        help="Kaggle replays usually record the response action on the next step.",
    )
    args = parser.parse_args()

    paths = expand_replay_glob(args.replay_glob)
    if not paths:
        raise SystemExit(f"No replay files matched: {args.replay_glob}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    clear_output_files(args.out_dir)
    card_names = load_card_names(args.card_csv)

    all_deck_rows: list[dict[str, Any]] = []
    all_deck_order_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    total_examples = 0
    jsonl_path = args.out_dir / "imitation_examples.jsonl"

    for path in paths:
        deck_rows, deck_order_rows, examples, summary = extract_replay(
            path,
            card_names,
            args.include_current,
            args.label_alignment,
        )
        all_deck_rows.extend(deck_rows)
        all_deck_order_rows.extend(deck_order_rows)
        append_jsonl(jsonl_path, examples)
        summaries.append(summary)
        total_examples += len(examples)

    write_deck_csv(args.out_dir / "deck_cards.csv", all_deck_rows)
    write_jsonl(args.out_dir / "deck_orders.jsonl", all_deck_order_rows)
    write_card_popularity_csv(args.out_dir / "card_popularity.csv", all_deck_rows)

    aggregate = {
        "replay_glob": args.replay_glob,
        "replay_files": len(paths),
        "deck_card_rows": len(all_deck_rows),
        "deck_order_rows": len(all_deck_order_rows),
        "imitation_examples": total_examples,
        "include_current": args.include_current,
        "label_alignment": args.label_alignment,
        "summaries": summaries,
    }
    write_json(args.out_dir / "summary.json", aggregate)

    print("replay_files", len(paths))
    print("deck_card_rows", len(all_deck_rows))
    print("deck_order_rows", len(all_deck_order_rows))
    print("imitation_examples", total_examples)
    print("saved", args.out_dir)


if __name__ == "__main__":
    main()
