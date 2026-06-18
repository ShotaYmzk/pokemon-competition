"""
リプレイデータ → 模倣学習データセット変換
==========================================
各ターンの obs（観測）と selected（選択したアクション）のペアを抽出する。

出力: JSONL形式
  {"replay_id": 80408508, "step": 5, "player": 0, "obs": {...}, "selected": [0], "select": {...}}
"""

import json
import argparse
from pathlib import Path
from tqdm import tqdm


def extract_training_pairs(replay: dict, player_filter: int | None = None):
    """
    replay_data の各ステップから (obs, selected) ペアを抽出。

    player_filter: 0か1を指定すると、そのプレイヤーの行動のみ抽出。
                   None なら両プレイヤー分。
    """
    pairs = []
    replay_id = replay["replay_id"]
    my_player_index = replay["my_player_index"]
    replay_data = replay["replay_data"]

    for step_idx, step in enumerate(replay_data):
        selected = step.get("selected")
        select = step.get("select")
        obs = step.get("obs")

        # selected が None か空ならスキップ（行動なしステップ）
        if selected is None or len(selected) == 0:
            continue
        if select is None or obs is None:
            continue

        # どのプレイヤーが行動しているかを特定
        # current.yourIndex が「このステップで行動するプレイヤー」
        current = step.get("current", {})
        acting_player = current.get("yourIndex", my_player_index)

        if player_filter is not None and acting_player != player_filter:
            continue

        # option が空のステップは意味のある学習データにならない
        options = select.get("option", [])
        if len(options) == 0:
            continue

        # selected はoption内のインデックスのリスト
        # 選択肢が1つしかない強制選択はスキップ（情報量がない）
        if len(options) == 1:
            continue

        pairs.append({
            "replay_id": replay_id,
            "step": step_idx,
            "player": acting_player,
            "ratings": replay.get("ratings", []),
            "select_type": select.get("type"),
            "select_context": select.get("context"),
            "n_options": len(options),
            "selected": selected,
            "select": select,
            "obs": obs,
        })

    return pairs


def main():
    parser = argparse.ArgumentParser(description="リプレイ → 学習データ変換")
    parser.add_argument("--input",  type=str, default="replays", help="リプレイJSONディレクトリ")
    parser.add_argument("--output", type=str, default="dataset.jsonl", help="出力JSONLファイル")
    parser.add_argument("--player", type=int, default=None, choices=[0, 1, None],
                        help="抽出するプレイヤー (0/1/None=両方)")
    parser.add_argument("--min-rating", type=int, default=0,
                        help="最小レーティングフィルタ")
    args = parser.parse_args()

    in_dir = Path(args.input)
    files = list(in_dir.glob("*.json"))
    print(f"リプレイファイル数: {len(files)}")

    total_pairs = 0
    with open(args.output, "w", encoding="utf-8") as f_out:
        for fpath in tqdm(files, desc="converting"):
            try:
                with open(fpath, encoding="utf-8") as f:
                    replay = json.load(f)

                # レーティングフィルタ
                ratings = replay.get("ratings", [])
                valid_ratings = [r for r in ratings if r is not None]
                if valid_ratings and min(valid_ratings) < args.min_rating:
                    continue

                pairs = extract_training_pairs(replay, player_filter=args.player)
                for pair in pairs:
                    f_out.write(json.dumps(pair, ensure_ascii=False, separators=(",", ":")) + "\n")
                total_pairs += len(pairs)

            except Exception as e:
                print(f"ERROR {fpath}: {e}")

    print(f"総学習ペア数: {total_pairs:,}")
    print(f"出力: {args.output}")


if __name__ == "__main__":
    main()
