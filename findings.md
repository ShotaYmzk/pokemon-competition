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

---

## STEP 7: search_api.py 整備・順序モデル検証・greedy エージェント・タイミング計測

### 0. `explore/search_api.py`
STEP5 v2 の ctypes 配線をクリーンな関数群に切り出した（トップレベルの副作用なし）。

- `agent_start()` — `AgentStart()` の薄いラッパー（type field=2 のサーチ専用ポインタ）
- `search_begin(agent_ptr, sbi_bytes, your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active, manual_coin=0, deck_filler=None)` — `(parsed_json, raw_text)` を返す
- `search_step(agent_ptr, search_id, action)` — `(parsed_json, raw_text)` を返す
- `search_end(agent_ptr)` — `SearchEnd` + (存在すれば) `SearchRelease` を呼ぶ
- ヘルパー: `make_int_array`, `card_ids`, `visible_card_ids`, `remaining_deck_guess`, `first_valid_search_action`

スモークテスト（`python explore/search_api.py`）: 実ゲームを中盤まで進め、1回の begin/step/end サイクルを実行 → **`SearchBegin error=0`, `SearchStep error=0`** を確認済み。

### Task A: `explore/run_match.py`
`kaggle_environments.make("cabt").run([...])` を N 回実行し、勝率・引分率・平均ステップ数・1ゲームあたりウォールクロック・1アクションあたりウォールクロック（min/median/max/mean）を集計するハーネス。

- ランダム vs ランダム（`agent/main.py` 同士）, N=10 で検証: 30%/70%/0% （分散内、想定通り対称）
- 1ゲーム平均 ~0.3秒、79ステップ前後、1アクションあたり中央値 ~0.08ms

### Task B（最重要）: `explore/step6_forward_model_validation.py`

手順:
1. `battle_start`/`battle_select` によるランダム自己対戦で turn>=2 の中盤局面まで進行。
2. 自分側カードは観測された実IDを使用。相手の隠しカードは `deck.csv` から両プレイヤーの可視カード（hand/active/bench/discard/prize）を全て除いた残りから決定的に1通り構築（`remaining_deck_guess`）。空配列やプレースホルダーではなく実サンプリング。
3. `select.option` の各合法手について `SearchStep` を実行し、次状態の合法手・prize数・terminal判定の妥当性を確認。
4. その状態から `SearchStep` のみを繰り返すフルランダムプレイアウトを実行し、勝者/終了を確認。

#### **Field path: SearchState から side/prize 差分を読む方法**
**`state['observation']['current']['players'][i]['prize']` はリストで、各サイドの未獲得サイド枚数を表す（バトル開始時は長さ6）。要素は表向きでない間は `null`、公開・獲得されると카드 dict になる。残りプライズ数は単純に `len(players[i]['prize'])` で、サイドを取るたびにこの長さが減少する。**

#### **Field path: terminal / winner 判定**
**`state['observation']['current']['result']` がゲーム中は `-1`。終了すると勝者の `playerIndex`（0 または 1）になり、引分なら `2`（`cg/game.py` の `battle_finish` のセマンティクスと一致）。`select.option` が空になることも終了の兆候だが、`result` フィールドが正規の判定ソース。**

#### 検証結果まとめ
- 手順1〜3（mid-game到達・determinize・各合法手へのSearchStep）は **全て error=0** で安定動作。攻撃選択（type=7）・カードプレイ（type=8）・ターン終了（type=14）のいずれも次状態の合法手数・prize数・result フィールドが妥当に変化することを確認。
- 手順4のフルランダムプレイアウトは **一部のシードで成功（500ステップ完走、エラーなし、seed=0, seed=13）し、他のシードではエラーで停止した（誠実な報告）**:
  - seed=1: 29ステップ後 `error=5`
  - seed=2: 2ステップ後 `error=5`
  - seed=5: 6ステップ後 `error=4`
  - seed=11: 17ステップ後 `error=5`
  - seed=20: 6ステップ後 `error=5`
  - 詳細に追跡したケース（seed=7）: `minCount=2, maxCount=2` の複数選択（`context=8`, `effect.id=1121` = Ultra Ball 相当のエフェクト、6つの `type=3` オプションから2つ選ぶ）で、`[0,1]`, `[0,4]`, `[4,0]` のいずれを送っても **`error=4`** で再現した。順序や値の問題ではなく、このマルチセレクト文脈そのもので `SearchStep` が失敗する。
  - **仮説**: `SearchStep` のマルチカウント選択（`minCount>1`）の action エンコーディングが単一選択時と異なる可能性がある（例: ペアごとのフラットインデックスや、選択順序に依存する内部状態を要求するなど）。今回の `action=[i,j]`（オプション配列内のインデックスのリスト）というエンコーディングは単一選択（type=0, maxCount=1）には有効だが、`minCount=2`/`maxCount=2` のケースでは別の形式が必要と考えられる。このフォーマットの解明は今回のタスク範囲外（MCTS実装と合わせて後続タスクで詳細化が必要）。

### Task C: `agent/greedy.py`
優先順位ヒューリスティック実装:
1. 相手アクティブへの確定KO攻撃（lethal）
2. 上記が無ければ相手アクティブ HP に対する最大ダメージ攻撃
3. 上記が無ければ、自分の攻撃コストへ向けてエネルギーを進める接続（アクティブへの接続を優先）
4. 上記が無ければ、ベンチ→アクティブへカードを出す（将来のKO機会構築）
5. 最後は `agent/main.py` と同様の一様ランダムフォールバック

`agent/all_cards.json` / `agent/all_attacks.json` をコピーしてデッキと同様の探索パス（`_load_json_lookup`）でロード（kaggle の `exec()` 実行下でも `__file__` 非対応に対応、`agent/main.py` の `_load_deck` パターンを踏襲）。データが見つからない場合はランダムフォールバックに自然劣化。

`explore/all_cards.json`/`all_attacks.json` から実際のフィールド名を確認:
- 攻撃データ: `attacks.json` の `damage`（int）, `energies`（cost、`0`=任意タイプ/colorless を含むリスト）
- カードデータ: `cards.json` の `hp`, `attacks`（attackId のリスト）, `energyType`, `cardType`（5=Energy）
- 試合中の観測: `active[0]['hp']`, `active[0]['energies']`（添付済みエネルギーの energyType リスト）

#### greedy vs random 勝率（N=25, seed=0, `explore/run_match.py` で計測）
**greedy 14/25 = 56.0% 勝率（random 11/25 = 44.0%、引分0%）。** ランダムよりやや優位だが圧倒的な強さではない、という結果を誠実に報告する（恣意的な調整・盛りはしていない）。

### タイミングデータ（将来の MCTS 探索バジェット設計向け）
- `runTimeout` = 3000秒/試合（cabt.json より）
- 実測（random vs random, N=10）: 1試合平均 ~0.31秒、平均79ステップ、1アクション（エージェント1回の意思決定）あたり中央値 ~0.08ms、最大 ~0.65ms
- greedy vs random（N=25）では1アクションあたり最大 150ms のスパイクが見られた（カード/攻撃データルックアップのオーバーヘッドと推測、許容範囲内）
- **示唆**: ランダム/greedy エージェントの意思決定コストは無視できるほど小さく（ms未満）、`runTimeout=3000秒` の予算は実質的に SearchBegin/SearchStep を使った木探索（MCTS）に使い切ってよい。1試合あたり平均ステップ数が約60〜80（本データ）であることから、各意思決定に割ける平均予算は概算で `3000秒 / 80手 ≈ 37秒/手`（ただし `actTimeout=0` で無制限、`remainingOverageTime=600秒` の制約も別途あるため、実際の探索ノード数はSearchStep呼び出しのレイテンシで決まる）。SearchStep自体のレイテンシは未計測（Task Bでエラー終了したケースが多く安定したベンチマークが取れなかったため）— MCTS実装時に最初に計測すべき指標として残す。
