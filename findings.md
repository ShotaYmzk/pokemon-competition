# PTCG AI Battle Challenge - 検証記録

最終更新: 2026-06-17

---

## STEP 0: 環境確認
- **OS**: Ubuntu 22.04 (Linux 6.8.0)
- **Python**: デフォルト 3.10.12 → Python 3.11.15 を deadsnakes PPA でインストール（必須: kaggle-environments が Python 3.11+ 要求）
- **Kaggle CLI**: 未インストール・未認証 → ローカル検証のみで進行
- **kaggle認証**: ~/.kaggle/kaggle.json 無し。提出はKaggleブラウザUIから行うこと

---

## STEP 1: シミュレータの特定とインストール

### 結論
- パッケージ名: `kaggle-environments==1.30.1`（2026-05-27 リリース）
- インストール: `pip install kaggle-environments`
- `cabt` 環境は kaggle-environments に同梱 (`envs/cabt/` ディレクトリ)
- APIドキュメント: https://matsuoinstitute.github.io/cabt/

### ファイル構成
```
kaggle_environments/envs/cabt/
├── cabt.json        # 環境設定 (episodeSteps=10000, actTimeout=0, runTimeout=3000)
├── cabt.py          # Python ゲームロジック
└── cg/
    ├── game.py      # battle_start/select/finish/visualize_data
    ├── sim.py       # ctypes バインディング（Battle クラス）
    └── libcg.so     # C++ 実装（Linux）/ cg.dll（Windows）
```

### 注意
- `api` モジュール（search_begin 等の高レベルラッパー）は **インストール済みパッケージに含まれない**
- search_* 関数は libcg.so を直接 ctypes 経由で呼ぶ必要がある

### 根拠URL
- https://pypi.org/project/kaggle-environments/
- https://matsuoinstitute.github.io/cabt/

---

## STEP 2: カードデータのダンプ

### 結果
- `AllCard()` → **1267 枚** (cardType: Pokemon=1056, Trainer=77+27+61+26+12, Energy=8 ほか)
- `AllAttack()` → **1556 件**
- 保存先: `explore/all_cards.json`, `explore/all_attacks.json`

### カードスキーマ（主要フィールド）
```json
{"cardId": 1, "name": "Basic {G} Energy", "cardType": 5, "pokemonType": 0,
 "evolutionType": 0, "retreatCost": 0, "hp": 0, "energyType": 1,
 "basic": false, "skills": [], "attacks": []}
```

### deck.csv との対応
- `deck.csv` には 60 行、各行にカードID（整数）を記載
- cabt.py のサンプルデッキは **61枚（バグ）** → 修正して60枚に

---

## STEP 3: 最小エージェントの作成

### ファイル
- `agent/main.py`: observation を受け取りランダム選択するエージェント
- `agent/deck.csv`: 60枚の合法デッキ (Kyogre/Snover/Mega Abomasnow ex + Basic W Energy ×33)

### 注意事項（重要）
- `kaggle-environments` は main.py を `exec()` で実行するため **`__file__` が未定義**
- `deck.csv` の探索は `sys.path` 経由で行う必要がある（修正済み）
- エージェント関数の最後の callable が自動検出される

### action 仕様
- デッキ選択フェーズ（`obs["select"] is None`）: 60枚のカードIDリストを返す
- 通常ターン: `random.sample(range(len(options)), maxCount)` でインデックスリストを返す

---

## STEP 4: ローカル自己対戦

### 結果
- **47ステップで正常完走** (0.1秒)
- Player 0 reward: -1 (DONE), Player 1 reward: 1 (DONE)
- 勝敗・終了判定が正常に機能

---

## STEP 5: 探索API（search_*）の疎通確認 ← 最重要

### **結論: SearchBegin / SearchStep / SearchEnd は全て呼べる（error=0）**

### 実証された呼び出し方（ctypes）

```python
import ctypes
from kaggle_environments.envs.cabt.cg.sim import lib

# 1. AgentStart() で search 専用ポインタを取得
lib.AgentStart.restype = ctypes.c_void_p
lib.AgentStart.argtypes = []
agent_ptr = lib.AgentStart()  # type field = 2

# 2. SearchBegin
lib.SearchBegin.restype = ctypes.c_char_p
lib.SearchBegin.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),  # your_deck
    ctypes.POINTER(ctypes.c_int),  # your_prize
    ctypes.POINTER(ctypes.c_int),  # opp_deck
    ctypes.POINTER(ctypes.c_int),  # opp_prize
    ctypes.POINTER(ctypes.c_int),  # opp_hand
    ctypes.POINTER(ctypes.c_int),  # opp_active
    ctypes.c_int,                  # manual_coin
]
sbi_bytes = obs["search_begin_input"].encode("ascii")
# 各 int* は見えているカードを除いた推定カードIDリスト（min_len でパディング）
result = lib.SearchBegin(agent_ptr, sbi_bytes, len(sbi_bytes),
    your_deck_arr, your_prize_arr, opp_deck_arr, opp_prize_arr,
    opp_hand_arr, opp_active_arr, 0)
# → {"state": {"observation": {...}}, "error": 0}

# 3. SearchStep(agent_ptr, search_id, action_ptr, action_len)
lib.SearchStep.restype = ctypes.c_char_p
lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.c_int]
step_result = lib.SearchStep(agent_ptr, 0, action_arr, len(action))
# → {"state": {...次状態...}, "error": 0}

# 4. SearchEnd
lib.SearchEnd.restype = None
lib.SearchEnd.argtypes = [ctypes.c_void_p]
lib.SearchEnd(agent_ptr)
```

### ハマりポイント（重要）
1. `SearchBegin` に `battle_ptr` を渡すと **error=30** (battle_ptr の type field = 1)
2. `SearchBegin` に `agent_ptr` (AgentStart() の戻り値、type field = 2) を渡すと正常動作
3. `search_begin_input` は base64 encoded バイナリ。`.encode("ascii")` で OK
4. 各 int* 引数は推定カードIDリスト（空でも動くが、観測から実カードIDを使うこと）
5. `SearchStep` の 2~4 番目引数: `(search_id: int, action: int*, action_len: int)`

### SearchState の構造（戻り値 JSON）
```json
{
  "state": {
    "observation": {
      "select": {"type": 0, "maxCount": 1, "option": [...]},
      "logs": [...],
      "current": {...}
    }
  },
  "error": 0
}
```
- `search_begin_input` フィールドは SearchState 内の observation には含まれない（Noneになる）
- `searchId_` は戻り値に無く、SearchStep の第2引数は 0 固定で OK（単一サーチチェーン）

---

## STEP 6: 提出物パッケージング

### 結果
```bash
cd agent && tar -czvf ../submission.tar.gz main.py deck.csv
```

- `submission.tar.gz` に `main.py` と `deck.csv` がトップ階層に存在することを確認済み
- ネストなし

---

## 制限・設定（cabt.json より）
| 項目 | 値 |
|---|---|
| episodeSteps | 10000 |
| actTimeout | 0 秒（無制限！） |
| runTimeout | 3000 秒（1試合上限） |
| remainingOverageTime | 600 秒 |
| 報酬 | 勝利: +1, 敗北: -1, 引分: 0 |

---

## 次に進めること / ブロッカー

**次に進めること:**
1. `search_begin` → `search_step` を複数回呼ぶ MCTS / 木探索エージェントの実装
2. `AllCard()` / `AllAttack()` のデータを活用したデッキ最適化（1267枚から選定）
3. SearchStep の戻り値（next_state.observation）をパースして合法手評価

**ブロッカー:**
- Kaggle 認証なし → 提出はブラウザUI経由（`~/.kaggle/kaggle.json` が必要なら設定要）
- 高レベル Python API (`api.search_begin()`) は未実装 → ctypes 直呼びで代替済み
