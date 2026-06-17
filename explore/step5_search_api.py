#!/usr/bin/env python3
"""STEP 5: search_begin / search_step / search_end 疎通確認 (最重要)"""

import ctypes
import json
import sys

from kaggle_environments.envs.cabt.cg.sim import lib, Battle
from kaggle_environments.envs.cabt.cg.game import battle_start, battle_select, battle_finish

print("=== STEP 5: Search API Verification ===\n")

# ---- デッキ読み込み ----
with open("agent/deck.csv") as f:
    deck = [int(l.strip()) for l in f if l.strip()]
assert len(deck) == 60

# ---- 対戦開始 ----
obs, start_data = battle_start(deck, deck)
if obs is None:
    print(f"[FAIL] battle_start failed: errorPlayer={start_data.errorPlayer} errorType={start_data.errorType}")
    sys.exit(1)
print(f"[OK] battle_start succeeded, battle_ptr={Battle.battle_ptr}")

# ---- 最初の観測を確認 ----
print(f"  obs keys: {list(obs.keys())}")
print(f"  obs['select']: {obs['select']}")
print(f"  search_begin_input length: {len(obs['search_begin_input']) if obs.get('search_begin_input') else 0}")

# デッキ選択フェーズをスキップするためにゲームを少し進める
# select=Noneの場合はデッキ選択 → デッキのカードIDリストを返す
step = 0
while obs["select"] is None:
    from kaggle_environments.envs.cabt.cg.game import battle_select
    obs = battle_select(deck)
    step += 1
    if step > 5:
        print("[FAIL] Stuck in deck selection phase")
        sys.exit(1)

print(f"\n[OK] Reached in-game state after {step} deck-selection steps")
print(f"  current.yourIndex: {obs['current']['yourIndex']}")
print(f"  current.result: {obs['current']['result']}")
print(f"  select.maxCount: {obs['select']['maxCount']}")
print(f"  select.option count: {len(obs['select']['option'])}")
print(f"  search_begin_input length: {len(obs.get('search_begin_input',''))}")

sbi = obs.get("search_begin_input", "")
print(f"  search_begin_input (first 100 chars): {sbi[:100]!r}")

# ---- SearchBegin の呼び出し ----
print("\n--- Trying SearchBegin ---")

# AgentStart() は検索API用の ApiData* を返す。
agent_ptr = None
try:
    lib.AgentStart.restype = ctypes.c_void_p
    lib.AgentStart.argtypes = []
    agent_ptr = lib.AgentStart()
    print(f"[OK] AgentStart() returned agent_ptr={agent_ptr}")
except Exception as e:
    print(f"[WARN] AgentStart() failed: {e}")

sbi_bytes = sbi.encode("ascii") if sbi else b""

# objdump 解析結果:
#   const char* SearchBegin(ApiData* agent,
#                           const char* search_begin_input, int input_len,
#                           int* ids0, int* ids1, int* ids2,
#                           int* ids3, int* ids4, int* ids5,
#                           int flag);
#   const char* SearchStep(ApiData* agent);
#   void SearchEnd(ApiData* agent);
#
# SearchBegin は第7-第9引数をスタックから読み、最後に [rsp+0x148] の
# int フラグも参照する。3引数呼び出しでは未定義のスタック値をポインタ
# として扱うためセグフォルトする。
lib.SearchBegin.restype = ctypes.c_char_p
lib.SearchBegin.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
]
lib.SearchStep.restype = ctypes.c_char_p
lib.SearchStep.argtypes = [ctypes.c_void_p]
lib.SearchEnd.restype = None
lib.SearchEnd.argtypes = [ctypes.c_void_p]

# 6本の int* は SearchStartConfig 用のカードIDリスト。各リストは C 側で
# 現在状態の必要枚数だけ読み出されるため、デッキ全体を渡して十分な長さを
# 確保する。
deck_arg = (ctypes.c_int * len(deck))(*deck)

print(f"  Trying SearchBegin(agent_ptr, sbi_bytes, len={len(sbi_bytes)}, six int* lists, flag=0) ...")
try:
    begin_json_bytes = lib.SearchBegin(
        agent_ptr,
        sbi_bytes,
        len(sbi_bytes),
        deck_arg,
        deck_arg,
        deck_arg,
        deck_arg,
        deck_arg,
        deck_arg,
        0,
    )
    begin_json = begin_json_bytes.decode() if begin_json_bytes else ""
    print(f"[OK] SearchBegin returned json (first 500): {begin_json[:500]!r}")
    if begin_json:
        begin_obs = json.loads(begin_json)
        print(f"  begin_obs keys: {list(begin_obs.keys())}")
except Exception as e:
    print(f"[FAIL] SearchBegin: {e}")
    import traceback; traceback.print_exc()
    begin_json = ""

try:
    if begin_json:
        # ---- SearchStep の呼び出し ----
        print("\n--- Trying SearchStep ---")
        step_json_bytes = lib.SearchStep(agent_ptr)
        step_json = step_json_bytes.decode() if step_json_bytes else ""
        print(f"[OK] SearchStep returned json (first 500): {step_json[:500]!r}")
        if step_json:
            step_obs = json.loads(step_json)
            print(f"  step_obs keys: {list(step_obs.keys())}")

        # ---- SearchEnd の呼び出し ----
        print("\n--- Trying SearchEnd ---")
        lib.SearchEnd(agent_ptr)
        print("[OK] SearchEnd called successfully")
    else:
        print("\n[FAIL] SearchBegin did not return JSON")
finally:
    if agent_ptr:
        lib.BattleFinish(agent_ptr)
    battle_finish()
print("\n=== STEP 5 Complete ===")
