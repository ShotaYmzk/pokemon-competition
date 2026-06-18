---
paths:
  - "**/*.py"
---

# エージェント実装ルール

## 必須実装
- すべての意思決定関数にタイムアウト処理を入れる
- カード情報は必ずJP_Card_Data.csvから動的に読み込む（ハードコード禁止）
- 例外処理を必ず書く（クラッシュ=試合負けになる）
- デッキ選択フェーズ: ゲーム冒頭で `obs["select"]` が `None` のとき、エージェントは60枚のカードIDリスト（`list[int]`）を返す。`deck.csv` は提出用の定義ファイルであり、実行時はこの分岐でデッキ内容を返す（`main.py` に必須）

```python
def agent(obs_dict: dict) -> list[int]:
    if obs_dict["select"] is None:
        return deck  # len(deck) == 60, 各要素はカードID（int）
    options = obs_dict["select"]["option"]
    max_count = obs_dict["select"]["maxCount"]
    # minCount <= len(indices) <= maxCount, 重複なし
    return [...]
```

## Kaggle 提出

- tar ルートに `main.py` + `deck.csv` が必須
- 複数ファイル構成時は `agent/` 等を tar に同梱可（`explore/` は含めない）
- 詳細: `.claude/rules/submission.md`

## コーディング規約
- 関数には必ずdocstringを書く
- カードIDは整数型で統一（CSV の「カードID」列）
- テストを書いてからロジックを実装する

## パフォーマンス
- 意思決定1回あたりの目安: 1秒以内
- 重い処理はキャッシュする
