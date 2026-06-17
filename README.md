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

## Kaggle 認証（未設定）
提出には `~/.kaggle/kaggle.json` が必要。
Kaggle サイト (https://www.kaggle.com/settings/account) から API キーを取得して配置すること。

## 提出

```bash
cd agent
tar -czvf ../submission.tar.gz main.py deck.csv
# → Kaggle コンペページからブラウザでアップロード
```

## 詳細な検証結果
→ `findings.md` を参照
