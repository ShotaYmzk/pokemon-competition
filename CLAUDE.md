# ポケモンTCG AI Battle Challenge

## プロジェクト概要
- シミュレーション部門 + ストラテジー部門の両方で上位入賞を目指す
- 提出はKaggle上でPythonエージェントとして行う
- カードデータ: `pokemon-tcg-ai-battle/JP_Card_Data.csv`（2022行、日本語）

## 締め切り
- Simulation: 2026/08/17 08:59 JST（1日5提出まで）
- Strategy: 2026/09/14 08:59 JST（1チーム1回のみ）

## よく使うコマンド
- 仮想環境: `source env/venv311/bin/activate`
- テスト: `python -m pytest tests/`
- エージェント実行: `python explore/run_match.py`
- デッキ検証: `python explore/step3_deck_check.py`
- 提出パッケージ: `cd agent && tar -czvf ../submission.tar.gz main.py deck.csv`

## コンペ絶対ルール（違反禁止）
- カードプールは `pokemon-tcg-ai-battle/JP_Card_Data.csv` の2022枚のみ使用可
- デッキは必ず60枚、同名カード4枚以下
- 1試合の制限時間は10分 → 意思決定に必ずタイムアウト処理を入れること
- ゲームエンジン自体は自作しない（主催者提供の環境を使う）
- カードの効果・数値を推測で実装しない（CSVの実データ参照必須）

## プロジェクト構造
- `agent/main.py`: メインエージェント（Kaggle提出用）
- `agent/deck.csv`: 提出デッキ
- `agent/mcts.py`, `agent/greedy.py`: エージェント実装
- `pokemon-tcg-ai-battle/JP_Card_Data.csv`: カードデータ（読み取り専用）
- `explore/`: 検証・実験スクリプト
- `tests/`: テストコード
