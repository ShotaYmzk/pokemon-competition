# Kaggle 提出パッケージ（submission.tar.gz）

公式サンプル: `pokemon-tcg-ai-battle/sample_submission/`
参考実装: リポジトリルートの `submission.tar.gz`

## 必須ファイル

### `main.py`（tar ルートに必須）

エントリーポイント。以下のシグネチャの `agent` 関数を定義する：

```python
def agent(obs_dict: dict) -> list[int]:
    # 初回: obs_dict["select"] is None → 60枚のカードIDリストを返す
    # 通常: obs_dict["select"]["option"] から maxCount 個のインデックスを返す
    return [...]
```

Kaggle 実行環境では `main.py` が `exec()` で読み込まれるため **`__file__` が未定義** になる場合がある。
パス解決は `os.getcwd()` / `sys.path` / `config.__raw_path__` を併用すること（`findings.md` STEP 3 参照）。

### `deck.csv`（tar ルートに必須）

60枚のカードIDを1行1枚で列挙（ヘッダーなし）：

```
278
278
...
7
7
```

## アーカイブ構造

```
submission.tar.gz
├── main.py          ← 必須・ルート
├── deck.csv         ← 必須・ルート
├── agent/           ← 複数ファイル構成時（helper モジュール群）
├── models/          ← 必要なら（例: value_net_best.pt）
└── cg/              ← cabt エンジン用（下記参照）
```

- **`main.py` は必ず tar ルート**（`./main.py`）。ネストした `agent/main.py` だけでは不可。
- ロジックを分割する場合、`agent/` や `models/` などを tar に同梱してよい。
- **`explore/` は開発用** — 提出 tar には含めない。

### `cg/` フォルダ

Kaggle ビギナーガイドおよび公式サンプル（`sample_submission/cg/`）参照。

- `cg/` には cabt エンジンの共有ライブラリ（`.so` 等）が入る
- 競技用データセット **cg-lib** からコピーして使う（自分で書くものではない）
- ローカル検証では `kaggle-environments` 同梱の cabt 環境を使う
- Kaggle 本番環境ではホスト側が提供する場合があり、提出 tar に含めない構成もある（要確認）

## `agent` 関数の動作仕様

| フェーズ | 条件 | 返り値 |
|---------|------|--------|
| デッキ選択 | `obs_dict["select"] is None` | `list[int]` — 60枚のカードID |
| 通常ターン | `obs_dict["select"]` が dict | `list[int]` — 選択肢インデックス |

通常ターンの制約（公式サンプルより）:

- 各要素は `0 <= index < len(obs_dict["select"]["option"])`
- 長さは `minCount <= len <= maxCount`（重複なし）
- `obs_dict["current"]` に盤面状態、`obs_dict["select"]` に選択可能な手

## ビルドコマンド

### 最小構成（単一ファイルエージェント）

```bash
cd agent
tar -czf ../submission.tar.gz main.py deck.csv
```

### 複数ファイル構成（現在の本番構成）

```bash
# 推奨
./explore/build_submission.sh

# 手動（リポジトリルートから）
tar -czf submission.tar.gz \
  --transform='s|^agent/main\.py$|main.py|' \
  --transform='s|^agent/deck\.csv$|deck.csv|' \
  agent/main.py agent/deck.csv \
  agent/mcts.py agent/mcts_agent.py agent/greedy.py \
  agent/search_api.py agent/features.py agent/value_net.py \
  models/value_net_best.pt
```

Kaggle CLI での提出手順: `.codex/kaggle-cli.md`

### 提出前チェック

```bash
tar -tzf submission.tar.gz
# ./main.py と ./deck.csv がルートにあることを確認
# deck.csv が60行であることを確認
python explore/step3_deck_check.py  # ローカル検証
```

## 開発構成との対応

| 開発パス | 提出 tar 内 |
|---------|------------|
| `agent/main.py` | `./main.py`（ルートにリネーム/配置） |
| `agent/deck.csv` | `./deck.csv` |
| `agent/*.py`（helper） | `./agent/*.py` など |
| `models/*.pt` | `./models/*.pt` |
| `explore/` | **含めない** |
| `pokemon-tcg-ai-battle/` | **含めない**（カードCSVは実行時に別途参照不可のため、必要データは tar 内に同梱） |

## rule-checker チェック項目（提出関連）

1. `deck.csv` が60行ちょうど
2. `main.py` に `agent` 関数が存在
3. デッキ選択フェーズ（`select is None`）の分岐がある
4. タイムアウト・例外処理がある（クラッシュ=敗北）
5. tar ルートに `main.py` / `deck.csv` がある（`tar -tzf` で確認）
