# 成果物保存ポリシー

Codex / Claude 共通。各 orchestrator はタスク完了時にこのルールに従うこと。

## 保存先一覧

| 成果物の種類 | 保存先 | 命名規則 | 例 |
|-------------|--------|----------|-----|
| デッキ案 | `agent/decks/legacy/` | `YYYY-MM-DD_<concept>.csv` | `2026-06-18_kyogre-snover-water.csv` |
| 提出デッキ確定 | `agent/deck.csv` | 上書き（rule-checker 通過後のみ） | — |
| 検証・実験結果 | `findings.md` | 日付見出しで追記 | STEP 4 形式を踏襲 |
| 設計判断（ADR） | `docs/decisions/` | `NNN-<topic>.md` | `001-mcts-timeout-strategy.md` |
| セッション要約 | `.codex/notes/` | `YYYY-MM-DD-<topic>.md` | Codex セッションの要点 |
| ベンチ・自己対戦ログ | `logs/` | 既存 JSONL 形式 | `self_play_10k.jsonl` |
| デッキ可視化 | `explore/deck_visualization/` | gitignore 対象 | `deck.html` |

## デッキ保存ルール

- 試作・比較用 → `agent/decks/legacy/YYYY-MM-DD_<concept>.csv`
- 提出確定 → `agent/deck.csv`（rule-checker PASS 後のみ上書き）
- 可視化確認: `python explore/visualize_deck.py --deck <path>`

## ADR（設計判断）ルール

- 場所: `docs/decisions/NNN-<topic>.md`
- 番号は連番（001, 002, ...）
- 含める内容: 背景・決定・理由・代替案

## エージェント完了時の必須アクション

1. 何を変更したか 1 段落で要約
2. 上表の該当パスに保存
3. `findings.md` または ADR に「なぜそうしたか」を 3 行以内で記録

## findings.md 追記フォーマット

```markdown
## YYYY-MM-DD: <タイトル>

- **変更**: ...
- **理由**: ...
- **検証**: 実行したコマンドと結果
```
