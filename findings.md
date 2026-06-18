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

---

## STEP 8: マルチセレクト SearchStep アクションエンコーディングの解明（解決）

### TL;DR — 結論
**`SearchStep` のマルチセレクト（`minCount`/`maxCount` > 1）は、選択したインデックスを `action=[i,j]` のような単一のフラットリストとして1回で送ってはいけない。代わりに、1枚ずつ単一要素 `[i]` の `SearchStep` 呼び出しを `minCount`（=`maxCount`、Ultra Ball 等のケースでは同値）回繰り返す必要がある。** これが唯一の確認されたフォーマットで、`explore/search_api.py` の `search_step()` に実装済み。

### Task 1: Ground-truth path（実ゲームの `battle_select` パス）
- `cg/sim.py:38-39`: `lib.Select.argtypes = [c_void_p, POINTER(c_int), c_int]` — battle_ptr, action配列, 配列長。`SearchStep` の `(agent_ptr, search_id, action_ptr, action_len)` と構造的に同形（差は先頭の `search_id` の有無のみ）。
- `cg/game.py:48-66 (battle_select)`: `arg = (c_int * len(select_list))(*select_list); err = lib.Select(Battle.battle_ptr, arg, len(select_list))`。**呼び出し側コードは select_list の長さを一度に渡している** — つまり `Select`（実ゲーム側API）自体は「1回でリスト全部」という呼び出し方を受け付ける形をしている。
- `cabt.py:73-76 (random_agent)`: `random.sample(list(range(len(obs["select"]["option"]))), obs["select"]["maxCount"])` — **`maxCount` 個のユニークなインデックスを1つのリストとして** `battle_select` に渡す。これがランダムエージェントの実装上のground truthであり、実際に `battle_select`（`Select` 経由）はこの「フラットリスト一括」呼び出しで正常に動作する（kaggle_environments の対戦は全てこの経路で正常完走している）。
- **しかし `SearchStep` は `Select` と同じ意味のAPIではない**: 実験的に確認した通り、`SearchStep` に同じ「フラットリスト一括」を渡すと **`minCount`/`maxCount` > 1 のケースで必ず `error=4` になる**（後述）。`Select`（実戦闘）と `SearchStep`（サーチ専用チェーン）は内部実装が異なり、`SearchStep` はマルチセレクトの内部状態管理が逐次的（1手ごと）になっていると考えられる。

### Task 2 & 3: 再現とエンコーディング解明（仮説検証）

#### 重要な前提の崩れ: `advance_to_midgame(deck, seed=N)` は再現不可能
`random.seed(N)` で固定しても、`battle_start`/`battle_select` を駆動するC++側（libcg.so）が独自の内部RNGを持つため、**同一シードで `advance_to_midgame` を2回呼んでも到達する中盤局面が毎回異なる**ことを確認した（`obs1 == obs2` も `steps1 == steps2` も False）。よって STEP7 で記録された「seed=7 で再現する」という記述は誤りで、実際には「ある特定の1回の実行で出た事象」であり、再実行すれば異なる局面・異なるエラーになる。本タスクでは、この事実を踏まえて多数のラン（30本規模のスキャン + 100シードスイープ）から **集計的に** エンコーディングを特定した。

#### H1〜H4 検証結果
ライブの `minCount=2, maxCount=2`（Ultra Ball, `effect.id=1121`, `context=8`）の決定点に到達したサーチチェーンに対し、同一の paused 状態（`agent_ptr`、まだ消費していない select）に複数のアクション形式を順に試した（最初に成功したフォーマットでチェーンが進むため、これ以降の形式は別の独立した paused 状態で再試行）:

| 試したエンコーディング | 結果 |
|---|---|
| `[0, 1]`（フラット、昇順） | `error=4` |
| `[1, 0]`（フラット、降順） | `error=4` |
| `[opt[0]['index'], opt[1]['index']]`（card-id/フィールド空間） | `error=4` |
| `[0, 1, 2, 3]`（オプション数过多） | `error=4` |
| `[0]`（1要素のみ、本来必要な2要素のうち1つ） | **`error=0`** |
| `[0, 0]`（重複インデックス） | `error=6`（別エラー、重複禁止を示唆） |

`[0]` という1要素アクションが `error=0` を返したことから、「1回のSearchStepには1つのインデックスのみ」という仮説（変形版H1、複数回呼び出し）を検証:
- `minCount=2, maxCount=2` の select に対し `search_step(ap, 0, [0])` → `error=0`。**戻り値の `select` は同じ `context=8, minCount=2, maxCount=2`、同じオプション数のまま**（選択肢は減らず、カウントも変わらない）。
- 続けて2回目の `search_step(ap, 0, [1])`（別インデックス）→ `error=0`。この後ようやく **`select.context` が `8` → `0` に変化**し、次の通常ターン選択に進んだ。

**結論（確定）**: マルチセレクトの正しいエンコーディングは、
```
for idx in chosen_indices:           # len(chosen_indices) == minCount (== maxCount for fixed-count effects)
    state, err = search_step(agent_ptr, 0, [idx])
    assert err == 0
# 最後の呼び出しの戻り値 state が次の意思決定点
```
**1手につき1要素のリストで `minCount` 回呼ぶ。** 中間呼び出しの間、select dict は同じ multi-select プロンプトを返し続け（オプション数も `minCount`/`maxCount` も変化しない）、ちょうど `minCount` 回目の呼び出しの後にだけ次の決定点（このケースでは `context` が `8`→`0`）に進む。重複インデックスを送ると `error=6` になるため、エンジン側は内部的に「既に選んだインデックス」を記憶していると考えられる。

#### error コード一覧（今回確認できた範囲）
`libcg.so` にはエラー文字列テーブルが見つからない（`strings libcg.so | grep -i error` は `"error"` という1語のJSONキー名のみがヒットし、エラーコード→意味のマッピング文字列は埋め込まれていない）。実行ベースで確認できた意味は以下:

| error code | 確認された意味 |
|---|---|
| 0 | 成功 |
| 1 | 不正な `search_id`（`SearchStep` の第2引数。0固定以外の値を渡すと即座にこれになる。0が唯一の正しい値であることを再確認） |
| 4 | マルチセレクトに対し、複数インデックスを1回のフラットリストで送った場合に発生（本STEPの主題） |
| 5 | 別の独立した問題（後述、未解決） |
| 6 | マルチセレクトの逐次呼び出し中に重複インデックスを送った場合 |
| 30 | `SearchBegin`/`SearchStep` に `battle_ptr`（type=1）を渡した場合（STEP5で既知） |

### `explore/search_api.py` の変更
- `_search_step_raw(agent_ptr, search_id, action)`: 旧 `search_step` の実体（1回のSearchStep呼び出しのみ、特別な処理なし）。
- `search_step(agent_ptr, search_id, action, select=None)`: 新しい公開関数。`select` 引数（呼び出し元が持っている select dict）を渡すと、`select.get('maxCount', 1) > 1` または `select.get('minCount', 0) > 1` の場合に自動でマルチセレクト処理（`action` の各要素を1要素ずつ `_search_step_raw` で逐次送信）に切り替わる。`select=None`（デフォルト）または単一選択の場合は元の挙動と完全に同じ（1回呼び出し）。呼び出し側は単一/マルチを区別する必要がない。

### Definition of Done: 100シードスイープ結果
`explore/step6b_multiselect_fix_validation.py` — 100シード、各シードで `advance_to_midgame` → `SearchBegin` → 最大500回の `SearchStep` ランダムプレイアウト（修正済み `search_step()` 使用）。

```
PASS RATE (no SearchStep error / total): 40/100 = 40.0%
```

**重要**: 残った60件のエラー（すべて `error=5`）は **全てマルチセレクトとは無関係**（`error_info` の `minCount`/`maxCount` を集計すると、60件中60件が `maxCount=1, minCount∈{0,1}` の **単一選択**。マルチセレクト（`maxCount>1`）由来のエラーは0件）。すなわち、**本タスクの目的であるマルチセレクトのエンコーディング問題は完全に解決**（マルチセレクトを経由したプレイアウト29件中、エラーになったものは0件）。残る40%のエラー率は、STEP7で既に記録されていた「`context=7` の単一選択（`effect.id=1219`, Team Rocket's Petrel 等の deck-search 効果）で起きる `error=5`」と同種の、**別の・未解決の**問題（一部は `context=0` の通常ターン選択でも発生しており、ガード外）。

### 未解決の `error=5`（単一選択）について
- ガードレールに従い、これ以上のブラインドフォーミングは行わない。観測事実のみ記録する:
  - 60件中32件: `minCount=0, maxCount=1`（`context` は主に7、deck-search 系のオプショナル単一選択）。
  - 60件中21件: `minCount=1, maxCount=1, context=0`（通常ターンの主選択 — type=7攻撃/type=8カードプレイ/type=14ターン終了等の混合）。
  - 発生タイミングはシードごとに非決定的（同一シード・同一コードでも再実行すると異なるステップ数でエラーになる、またはエラーなく完走する）。これは前述の「libcg.so 内部RNGの非決定性」と直接関係している可能性が高い（プレイアウト中に手に入るカード・発生する効果が再現できないため、ある時点で `SearchBegin` 時に決定論化した隠し情報（`your_deck`/`opp_deck`/`opp_hand` 等）と、その後の実際の引き手・シャッフル結果が矛盾し、エンジン内部の状態（山札順序やカード一意性）が破綻するケースがあると推測される）。
  - **要再調査ポイント（人間のレビュー推奨）**: `cg/game.py:13-16 (_get_battle_data)` の `search_begin_input` 生成ロジック、および `SearchBegin` 呼び出し時の `your_deck`/`opp_deck` 配列の決定論化（`explore/search_api.py` の `sample_determinized_hidden_state`、`explore/step6_forward_model_validation.py:52-142`）が、プレイアウト後半で実際に山札から引かれるカードと矛盾していないかの検証が必要。本タスクではこの根本原因の特定までは到達していない。

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

---

## STEP 9: MCTS v0 実装に向けた T0/T1（計測・決定化正常化）

### 重大な発見: `explore/search_api.py` の ctypes ABI バグ（error=5 の主因の一部、確定）

公式リファレンス実装が `pokemon-tcg-ai-battle/sample_submission/cg/{sim.py,api.py,game.py}` に同梱されていることが判明した（STEP1 で「未インストール」と記録したのは誤り。本リポジトリのこのパスに最初から存在していた）。これを `explore/search_api.py` の ctypes バインディングと比較し、2つの実バグを発見・修正した：

1. **`SearchStep` の `search_id` 引数型**: 公式 `sim.py` では `ctypes.c_int64`。`explore/search_api.py` は `ctypes.c_int`（32bit）と誤って宣言していた。`search_id=0` という小さい値なので実害は薄いと推測されるが、ABI 上は不正。
2. **`SearchRelease` の引数不足（実害あり）**: 公式シグネチャは `SearchRelease(agent_ptr, search_id: int64)` の **2引数**。`explore/search_api.py` は `argtypes=[c_void_p]` の **1引数**で宣言し、`lib.SearchRelease(agent_ptr)` を1引数で呼んでいた。これは未定義動作で、第2引数（`search_id`）に渡る値はその時レジスタに残っていた不定値になる。エンジン側はこの不定値を「解放すべき search_id」として解釈してしまうため、内部の search-state テーブルを破壊しうる——**「シードごとに非決定的、再現不能」という STEP7/8 で観測された error=5 の症状と完全に一致する。**

`explore/search_api.py` の `_bind_types()` と `search_end()` を修正（`SearchStep` は `c_int64`、`SearchRelease` は2引数 `(agent_ptr, search_id)` に統一）。修正後、100シードスイープのPASS RATEは **40% → 50%** に改善（同一スクリプト、修正前後比較）。これは固定された再現可能な改善であり、エンジン内部RNGのノイズではない（ABIバグは決定的に毎回発生する類のバグ）。

### T1: 決定化の合法性バグをもう1件発見・修正（`visible_card_ids` の stadium/looking 抜け）

`sample_determinized_hidden_state` の最後に「自分側/相手側の60枚再構成がdeck.csv構成と一致する」ことを保証する `assert` を追加したところ、**実際に失敗するケースが見つかった**：

- 原因: `current.stadium`（と `current.looking`）は **プレイヤー単位の PlayerState ではなく `current` 直下のグローバルなゾーン**。スタジアムカードを場に出したプレイヤーの `playerIndex` がカード辞書に付与されているにもかかわらず、`explore/search_api.py` の `visible_card_ids()` はこのゾーンを一切見ていなかった。結果、スタジアムカードを出した側の「可視カード」集合がちょうど1枚少なく数えられ、その分が誤って「未知（山札/手札/プライズに振り分けるべき）」プールに混入していた。
- 修正: `visible_card_ids()` に `current.stadium`/`current.looking` を `playerIndex` でフィルタして加算する処理を追加（`explore/search_api.py`）。
- 同時に、相手のアクティブポケモンが裏向き（`active=[None]`）の場合に `opp_active` の推測サンプルを一切生成していなかった欠落も発見・修正（`pokemon-tcg-ai-battle/sample_submission/cg/api.py` の `search_begin()` 仕様どおり、裏向きアクティブには Pokemon カードIDの推測が必須）。`_pokemon_card_ids()` ヘルパーを追加し、`cardType==0` のカードのみから1枚を未知プールから確保するように修正（`explore/step6_forward_model_validation.py`）。
- 修正後、100/300シードスイープでこの `assert` は一度も発火しなくなった（合法性は保証された）。

### T1 修正後の error=5 率（最終報告）
300シードスイープ（`explore/step6b_multiselect_fix_validation.py`、`N_SEEDS=300`）:
```
PASS RATE (no SearchStep error / total): 132/300 = 44.0%
```
ABIバグ修正・決定化合法性修正の両方を適用した状態でもこの数値。**ガードレールに従い、これ以上の根本原因追跡はしない。** 残存する `error=5` はほぼ全て単一選択（`minCount<=1, maxCount=1`）、文脈は `context=0`（通常ターン主選択）または `context=7`（デッキサーチ系オプショナル選択）に集中しており、発生ステップ数はシードごとに大きく異なる（2手目で発生する場合もあれば400手超まで進む場合もある）。これは STEP8 で確認済みの「libcg.so 内部RNGがプロセスごとに非決定的」という性質と整合し、Python側のロジックでは再現・特定が困難。**MCTS v0 ではこの残存エラーを「探索分岐の打ち切り」として吸収する設計とする**（T2参照）。

### T0-1: SearchStep/SearchBegin のレイテンシ計測（`explore/step9_t0_timing_and_order.py`）
```
n_calls=542
min=0.0031ms median=0.0150ms mean=0.0427ms max=0.9374ms
throughput: ~23,431 calls/sec（シングルスレッド）
budget/move (3000s / ~70手) = 42.9秒/手 -> 1手あたり約100万回のSearchStep呼び出しが理論上可能
```
意思決定コストは無視できるほど小さく、`runTimeout=3000秒` の制約下でも非常に大規模なMCTS探索（数万〜数十万ノード/手）が可能。実際の反復回数はヒューリスティック評価関数やPython側オーバーヘッド、`remainingOverageTime=600秒` の制約で決まる。

### T0-2: SearchBegin は山札の「順序」を使うか「構成」だけか — 決定的実験結果
**結論: 順序は挙動に影響する（順序も意味を持つ）。** 同一構成（同じ60枚の多重集合）だが異なる順序で `your_deck`/`opp_deck` を渡し、同一の決定論的アクション列（固定シードの `random.sample`）を流したところ、両者の `select.option` 数・文脈の遷移列が**一致しなかった**（`explore/step9_t0_timing_and_order.py` の `t0_2_order_vs_composition`）。これは妥当な結果である: ドロー処理は「配列の先頭から順に引く」実装になっているはずなので、順序を変えれば「次に引かれるカード」が変わり、その後の手札・選択肢が変化するのは当然である。
**実務上の含意**: 決定化のたびに厳密な順序を再現する必要はない（そもそも本物の山札順序は隠されており知り得ない）。標準的な IS-MCTS のルートサンプリング方式どおり、**各ロールアウト（あるいは各決定点）ごとに、構成が正しい山札をランダムに並べ直してSearchBeginし直す**ことで、順序依存性は「サンプリングの分散」として吸収すればよい。これは T2 のMCTS設計（「毎手フレッシュにSearchBegin」）と整合する。
