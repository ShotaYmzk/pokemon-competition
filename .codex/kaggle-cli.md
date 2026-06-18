# Kaggle CLI 提出手順（pokemon-tcg-ai-battle）

コンペ ID: `pokemon-tcg-ai-battle`
提出形式: `submission.tar.gz`（ルートに `main.py` + `deck.csv` 必須）

パッケージ内容の詳細は `.codex/submission.md` を参照。

## 前提：セットアップ

### 1. Kaggle CLI（Python 3.11 venv 必須）

`pip install kaggle`（1.7.x）の **システム版は使わない**。新トークン（`KGAT_...`）は **Kaggle CLI 2.x + Python 3.11+** が必要。

```bash
source env/venv311/bin/activate
pip install 'git+https://github.com/Kaggle/kaggle-cli.git'   # → kaggle 2.2.x
kaggle --version   # Kaggle CLI 2.2.2 など
```

以降の `kaggle` コマンドは次のいずれかで実行する:

```bash
# 方法 1: venv を activate
source env/venv311/bin/activate
kaggle competitions list -p 1

# 方法 2: プロジェクトラッパー（activate 不要）
./bin/kaggle competitions list -p 1

# 方法 3: PATH に追加（このリポジトリ内で常に有効にしたい場合）
export PATH="$(pwd)/bin:$PATH"
```

**注意**: `~/.local/bin/kaggle`（1.7.x）は新トークン非対応。上記を使うこと。

### 2. API トークン

[Kaggle Settings → API](https://www.kaggle.com/settings/api) で **Generate New Token**。

**方法 A（推奨）: access_token ファイル**

```bash
mkdir -p ~/.kaggle
echo 'KGAT_xxxxxxxx' > ~/.kaggle/access_token   # トークンを貼る
chmod 600 ~/.kaggle/access_token
```

**方法 B: 環境変数**

```bash
export KAGGLE_API_TOKEN=KGAT_xxxxxxxx
```

**方法 C（レガシー）: kaggle.json**

Settings の **Legacy API Credentials → Create Legacy API Key** で取得。配置先は `~/.kaggle/kaggle.json`（`~/.config/kaggle/` ではない）。

```bash
mkdir -p ~/.kaggle
mv kaggle.json ~/.kaggle/
chmod 600 ~/.kaggle/kaggle.json
```

動作確認（venv311 内）:

```bash
source env/venv311/bin/activate
kaggle competitions list -p 1
```

**よくある失敗**:
- システムの `kaggle`（1.7.x）を使っている → `Could not find kaggle.json`
- 新トークンを `kaggle.json` の `key` に入れた → レガシー形式と不一致
- `YOUR_USERNAME` / `YOUR_KEY` のプレースホルダーをそのまま使っている

### 3. コンペ参加（初回のみ・Web UI 必須）

https://www.kaggle.com/competitions/pokemon-tcg-ai-battle で **Join Competition** を押す。
ルール未同意だと CLI 提出時に `rules not accepted` エラーになる。

参加確認:

```bash
kaggle competitions list --group entered | grep pokemon-tcg
```

## 提出フロー

### 1. アーカイブをビルド

```bash
# 推奨: ビルドスクリプト（ルートに main.py / deck.csv を正しく配置）
./explore/build_submission.sh

# 手動の場合（リポジトリルートで実行）
tar -czf submission.tar.gz \
  --transform='s|^agent/main\.py$|main.py|' \
  --transform='s|^agent/deck\.csv$|deck.csv|' \
  agent/main.py agent/deck.csv \
  agent/mcts_agent.py agent/mcts.py agent/value_net.py \
  agent/features.py agent/greedy.py agent/search_api.py \
  models/value_net_best.pt
```

中身確認（`main.py` がルート、`agent/` はサブディレクトリ）:

```bash
tar -tzf submission.tar.gz
```

ローカル検証:

```bash
source env/venv311/bin/activate
python explore/step3_deck_check.py
```

### 2. 提出

```bash
source env/venv311/bin/activate
./explore/build_submission.sh

kaggle competitions submit pokemon-tcg-ai-battle \
  -f submission.tar.gz \
  -m "MCTS v1 - greedy baseline"
```

- `-m` はメモ（バージョン管理用）。Simulation 部門は **1日5回まで**。

### 3. ステータス確認

```bash
kaggle competitions submissions pokemon-tcg-ai-battle
```

表示される **Submission ID** をメモする。

### 4. エピソード確認・デバッグ

```bash
# 自分の Submission ID でエピソード一覧
kaggle competitions episodes <submission_id>

# リプレイ取得
kaggle competitions replay <episode_id>

# ログ取得（agent_index=0 が自分、1 が相手）
kaggle competitions logs <episode_id> 0
```

### 5. リーダーボード

```bash
kaggle competitions leaderboard pokemon-tcg-ai-battle -s
```

### 6. 上位チームのエピソードを覗く

```bash
kaggle competitions team-submissions <team_id>
kaggle competitions episodes <their_submission_id>
kaggle competitions replay <their_episode_id>
```

## よくある失敗パターン

### `tar` のパス問題（最多）

ルート外からディレクトリごと tar すると `myproject/main.py` になり Kaggle で拒否される。

```bash
# NG（ディレクトリ外から）
tar -czf submission.tar.gz myproject/

# OK（main.py をルートに出す）
./explore/build_submission.sh
# または --transform で agent/main.py → main.py にリネーム
```

### `cg/` について

公式サンプルには `cg/` があるが、本リポジトリの MCTS 構成では **含めない**。
Kaggle 本番はホスト側が cabt エンジンを提供する。ローカル検証は `kaggle-environments` を使う。

### 認証エラー

```
Could not find kaggle.json
```

→ 上記「API キー」手順を完了する。

### ルール未同意

```
You must accept the competition rules before submitting
```

→ ブラウザでコンペに Join する。
