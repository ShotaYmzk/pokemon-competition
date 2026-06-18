# PTCG AI Battle Challenge - 環境構築・検証記録

## セットアップ

```bash
# Python 3.11 インストール（必須）
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.11 python3.11-venv

# 仮想環境作成・パッケージインストール
python3.11 -m venv env/venv311
source env/venv311/bin/activate
pip install kaggle-environments

# カードデータ取得
python explore/step2_card_data.py

# 自己対戦テスト
python explore/step4_selfplay.py

# 探索API検証
python explore/step5_v2_search_api.py
```

## Kaggle 認証

トークンは `~/.kaggle/access_token` に配置済み。`kaggle` コマンドは 2.2.x（`kaggle --version` で確認）。

```bash
kaggle competitions list -p 1   # 動作確認
# または ./bin/kaggle ... （venv 未 activate 時）
```

詳細: `.codex/kaggle-cli.md`

## 提出

```bash
source env/venv311/bin/activate
./explore/build_submission.sh
tar -tzf submission.tar.gz

kaggle competitions submit pokemon-tcg-ai-battle \
  -f submission.tar.gz \
  -m "your message"
```

## デッキ可視化（カード画像つきで確認）

`agent/deck.csv` はカードIDの数字だけで何が入っているか分かりにくいので、
カード名・画像つきのレポートを生成するツールがある。

```bash
source env/venv311/bin/activate
python explore/visualize_deck.py
```

出力先（`explore/deck_visualization/` に生成、`.gitignore` 対象）:
- `deck.html` — ブラウザで開く。カード画像・名前・枚数を「たね/1進化/2進化」「グッズ」
  「サポート」「スタジアム」「基本エネルギー」ごとにグループ表示。
  60枚チェック・同名カード4枚超チェックも自動表示される。
- `deck_grid.png` — 一覧確認用の合成画像（チャット等にそのまま貼れる）。

別のデッキ案を確認したい場合は `--deck` で別CSVを指定:

```bash
python explore/visualize_deck.py --deck agent/deck_v2.csv --out explore/deck_visualization_v2
```

仕組み: `pokemon-tcg-ai-battle/JP_Card_Data.csv` からカード名・種類を取得し、
`Card_ID List_JP.pdf` 内の該当カードの券面画像を切り出して埋め込んでいる
（PDFの読み込みに `pymupdf` を使用、未インストールなら `pip install pymupdf`）。

## 詳細な検証結果
→ `findings.md` を参照
