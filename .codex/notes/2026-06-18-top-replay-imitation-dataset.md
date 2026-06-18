# 2026-06-18 Top Replay Imitation Dataset

## Summary

Built a small top-leaderboard replay dataset pipeline for `pokemon-tcg-ai-battle`.

- `datasets/collect_top_replays.py`: uses Kaggle CLI to collect leaderboard rows, team submissions, public episodes, and replay JSON files.
- `datasets/extract_replay_dataset.py`: extracts deck order/counts and imitation-learning decision rows from Kaggle replay `steps`.
- `datasets/top_replays/`: current sample dataset from top 5 teams, 10 public replays.

## Commands Run

```bash
python -m py_compile datasets/collect_top_replays.py datasets/extract_replay_dataset.py
python datasets/collect_top_replays.py --top-teams 5 --episodes-per-submission 2 --max-replays 10 --out-dir datasets/top_replays
python datasets/extract_replay_dataset.py --replay-glob 'datasets/top_replays/replays/*.json' --out-dir datasets/top_replays/extracted
```

The collection command requires network access for Kaggle CLI.

## Outputs

- `datasets/top_replays/leaderboard_rows.json`
- `datasets/top_replays/submission_rows.json`
- `datasets/top_replays/episode_rows.json`
- `datasets/top_replays/downloaded_replays.json`
- `datasets/top_replays/replays/*.json`
- `datasets/top_replays/extracted/deck_orders.jsonl`
- `datasets/top_replays/extracted/deck_cards.csv`
- `datasets/top_replays/extracted/card_popularity.csv`
- `datasets/top_replays/extracted/imitation_examples.jsonl`
- `datasets/top_replays/extracted/summary.json`

## Current Dataset Stats

- Replays: 10
- Decks: 20
- Deck card rows: 357
- Imitation candidate rows: 4226
- Valid select-action rows: 2154
- Forced selects: 494
- Deck validation failures: 0

## Important Decisions

- Use `next-step` action alignment by default because Kaggle replay `steps[i].action` is the action returned after the previous observation.
- Preserve `deck_order` as well as `deck_counts`; SearchBegin experiments show deck order affects rollouts.
- Keep invalid/empty rows with explicit flags (`action_kind`, `valid_select_action`) so training can filter without losing auditability.
