# ポケモンTCG AI Battle Challenge

## プロジェクト概要
- シミュレーション部門 + ストラテジー部門の両方で上位入賞を目指す
- 提出はKaggle上でPythonエージェントとして行う
- カードデータ: `pokemon-tcg-ai-battle/JP_Card_Data.csv`（2,022行・日本語）+ `Card_ID List_JP.pdf`（カードID 1–1,267）。**使用可能なユニークカードは約1,267種**（CSV行数≠カード枚数。詳細は下記）

## 締め切り
- Simulation: 2026/08/17 08:59 JST（1日5提出まで）
- Strategy: 2026/09/14 08:59 JST（1チーム1回のみ）

## よく使うコマンド
- 仮想環境: `source env/venv311/bin/activate`
- テスト: `python -m pytest tests/`
- エージェント実行: `python explore/run_match.py`
- デッキ検証: `python explore/step3_deck_check.py`
- 提出パッケージ: `.claude/rules/submission.md` 参照（`tar -tzf submission.tar.gz` で確認）

## コンペ絶対ルール（違反禁止）

### カードプール
- 使用可能なのは **Kaggle Strategy ページ Data セクションで指定されたカードリスト内のカードのみ**（FAQ 明記）
- 参照データ: `pokemon-tcg-ai-battle/JP_Card_Data.csv` + `Card_ID List_JP.pdf`
- CSV は **2,022行** だが、ワザが複数あるカードは行が分かれるため **1行＝1カードではない**
- **ユニークカードIDは 1–1,267（約1,267種）**。`AllCard()` のスモークテスト結果とも一致
- デッキに入れてよいのはこの ID 集合に含まれるカードのみ

### デッキ
- 60枚ちょうど、同名カード最大4枚（基本エネルギー ID 1–8 は枚数制限なし）
- **デッキは人間が事前に決め打ちして submit してよい**（FAQ: AI にデッキ構築させる必要はない）。対戦行動のみ AI が担当
- デッキ選択は MCTS 開発と**別軸のオフライン最適化問題**として進めてよい

### その他
- 1試合の制限時間は10分 → 意思決定に必ずタイムアウト処理を入れること
- ゲームエンジン自体は自作しない（主催者提供の環境を使う）
- カードの効果・数値を推測で実装しない（CSV / エンジン API の実データ参照必須）

## プロジェクト構造
- `agent/main.py`: メインエージェント（Kaggle提出用）
- `agent/deck.csv`: 提出デッキ
- `agent/mcts.py`, `agent/greedy.py`: エージェント実装
- `pokemon-tcg-ai-battle/JP_Card_Data.csv`: カードデータ（読み取り専用）
- `explore/`: 検証・実験スクリプト
- `tests/`: テストコード

## AI エージェント設定

### Codex CLI
- プロジェクト指示: `AGENTS.md`（Codex 自動読み込み）
- 設定: `.codex/config.toml`
- 提出ルール: `.codex/submission.md`
- サブエージェント: `.codex/agents/*.toml`（gpt-5.5 / 5.4 / 5.4-mini）
- セッション要約: `.codex/notes/`
- スキル: `.agents/skills/`（`.claude/skills/` への symlink）

### Claude Code
- ルール: `.claude/rules/`（competition, agent, deck, submission, orchestration, artifacts）
- サブエージェント: `.claude/agents/*.md`（Opus / Sonnet / Haiku）
- スキル: `.claude/skills/`

### オーケストレーション
- Claude: `.claude/rules/orchestration.md`
- Codex: `.codex/agents/orchestrator.toml`

### 成果物保存
- 共通ポリシー: `.claude/rules/artifacts.md`
- デッキ試作: `agent/decks/legacy/`
- 検証記録: `findings.md`
- 設計判断: `docs/decisions/`
- ベンチログ: `logs/`
