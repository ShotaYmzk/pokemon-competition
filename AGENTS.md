# ポケモンTCG AI Battle Challenge

## コンペ絶対ルール（違反禁止）

### カードプール
- 使用可能: Kaggle 指定カードリスト内のみ（約1,267種、カードID 1–1,267）
- 参照: `pokemon-tcg-ai-battle/JP_Card_Data.csv`（2,022行＝ワザ行含む。ユニークカード数ではない）
- リスト外のカードIDは使用不可

### デッキ
- 60枚、同名4枚以下（基本エネルギー ID 1–8 は枚数制限なし）
- デッキは人間が事前決定して submit 可（AI は対戦行動のみ担当可）

### その他
- 1試合の制限時間は10分 → 意思決定に必ずタイムアウト処理を入れること
- ゲームエンジン自体は自作しない（主催者提供の `kaggle-environments` / cabt 環境を使う）
- カードの効果・数値を推測で実装しない（CSV / エンジン API の実データ参照必須）
- 主催者提供以外のゲームシミュレーターを使わない
- Simulation: 1日5提出まで / Strategy: 1チーム1回のみ

## プロジェクト構造・コマンド

### 主要パス

- `agent/main.py`: メインエージェント（Kaggle提出用）
- `agent/deck.csv`: 提出デッキ（60行、ヘッダーなし）
- `agent/mcts.py`, `agent/greedy.py`: エージェント実装
- `pokemon-tcg-ai-battle/JP_Card_Data.csv`: カードデータ（読み取り専用）
- `explore/`: 検証・実験スクリプト
- `tests/`: テストコード

### よく使うコマンド

```bash
source env/venv311/bin/activate
python -m pytest tests/
python explore/run_match.py
python explore/step3_deck_check.py
./explore/build_submission.sh   # submission.tar.gz ビルド
# 提出: .codex/kaggle-cli.md / パッケージ: .codex/submission.md
tar -tzf submission.tar.gz      # 提出前: main.py / deck.csv がルートにあること
```

## 提出パッケージ（要点）

- tar ルートに `main.py` + `deck.csv`（60行）が必須
- `agent()` は初回 `select is None` でデッキ60枚、通常は `select.option` からインデックスを返す
- 複数ファイル構成時は `agent/` 等を同梱可。`explore/` は含めない
- 詳細: `.codex/submission.md` / `.claude/rules/submission.md`

## 詳細参照

- プロジェクト全体: `CLAUDE.md`
- ルール詳細: `.claude/rules/`
- 提出パッケージ: `.codex/submission.md` / `.claude/rules/submission.md`
- オーケストレーション: `.claude/rules/orchestration.md` / `.codex/agents/`
- 成果物保存: `.claude/rules/artifacts.md`
