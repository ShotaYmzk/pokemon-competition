"""
ptcgvis.heroz.jp リプレイスクレイパー
=====================================
使い方:
    pip install requests tqdm
    python scrape_replay.py --start 80000000 --end 80500000 --out replays/

仕組み:
    POST https://ptcgvis.heroz.jp/Visualizer/Replay/{id}/0
    → HTMLの <script> タグ内に replayData = [...] が埋め込まれている
    → 正規表現で抽出してJSONとして保存
"""

import re
import json
import time
import random
import argparse
import logging
from pathlib import Path

import requests
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# =========== 設定 ===========
BASE_URL = "https://ptcgvis.heroz.jp/Visualizer/Replay/{replay_id}/0"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.kaggleuserContent.com",
    "Referer": "https://www.kaggleuserContent.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
}

# ps（プレイヤー名）からレーティングを取得
# "[Win] onechan1 1298 (+10)" のような形式
RATING_RE = re.compile(r"\[(?:Win|Loss)\]\s+\S+\s+(\d+)")


# =========== コア関数 ===========

def extract_json_array(html: str, varname: str = "replayData") -> str | None:
    """ブラケットのネスト深度を数えてJSONを確実に抽出する"""
    start_marker = f"var {varname} = "
    pos = html.find(start_marker)
    if pos == -1:
        return None
    pos += len(start_marker)
    while pos < len(html) and html[pos] not in '[{;':
        pos += 1
    if pos >= len(html) or html[pos] == ';':
        return None

    depth = 0
    in_string = False
    escape_next = False
    start = pos

    for i, c in enumerate(html[pos:], start=pos):
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c in '[{':
                depth += 1
            elif c in ']}':
                depth -= 1
                if depth == 0:
                    return html[start:i+1]
    return None


def fetch_replay(session: requests.Session, replay_id: int, timeout: int = 15) -> dict | None:
    """
    1件のリプレイデータを取得して返す。
    失敗時は None。
    """
    url = BASE_URL.format(replay_id=replay_id)
    try:
        resp = session.post(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            log.debug(f"[{replay_id}] HTTP {resp.status_code}")
            return None

        html = resp.text

        # replayData を抽出
        raw = extract_json_array(html, "replayData")
        if not raw:
            log.debug(f"[{replay_id}] replayData not found in HTML")
            return None

        replay_data = json.loads(raw)

        # myPlayerIndex を抽出
        mi = re.search(r"var\s+myPlayerIndex\s*=\s*(\d+)", html)
        my_player_index = int(mi.group(1)) if mi else 0

        # レーティングを取得（replayData[0].ps から）
        ps = replay_data[0].get("ps", [])
        ratings = []
        for p in ps:
            rm = RATING_RE.search(str(p))
            ratings.append(int(rm.group(1)) if rm else None)

        return {
            "replay_id": replay_id,
            "my_player_index": my_player_index,
            "ps": ps,
            "ratings": ratings,
            "replay_data": replay_data,
        }

    except (requests.RequestException, json.JSONDecodeError, Exception) as e:
        log.debug(f"[{replay_id}] error: {e}")
        return None


def get_min_rating(result: dict) -> int:
    """両プレイヤーのうち低い方のレーティングを返す（フィルタ用）"""
    ratings = [r for r in result.get("ratings", []) if r is not None]
    return min(ratings) if ratings else 0


# =========== メイン ===========

def main():
    parser = argparse.ArgumentParser(description="PTCG Visualizer replay scraper")
    parser.add_argument("--start", type=int, required=True, help="開始replay ID")
    parser.add_argument("--end",   type=int, required=True, help="終了replay ID")
    parser.add_argument("--out",   type=str, default="replays", help="保存ディレクトリ")
    parser.add_argument("--min-rating", type=int, default=1300,
                        help="この値以上のレーティングの対戦のみ保存 (default: 1300)")
    parser.add_argument("--delay-min", type=float, default=0.3,
                        help="リクエスト間隔の最小秒数 (default: 0.3)")
    parser.add_argument("--delay-max", type=float, default=0.8,
                        help="リクエスト間隔の最大秒数 (default: 0.8)")
    parser.add_argument("--step", type=int, default=1,
                        help="IDのステップ (1=全件, 10=間引き)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = range(args.start, args.end + 1, args.step)
    saved = 0
    skipped_rating = 0
    failed = 0

    log.info(f"スキャン範囲: {args.start} ~ {args.end} (step={args.step})")
    log.info(f"最小レーティング: {args.min_rating}")
    log.info(f"保存先: {out_dir}")

    with requests.Session() as session:
        for replay_id in tqdm(ids, desc="scraping"):
            result = fetch_replay(session, replay_id)

            if result is None:
                failed += 1
            elif get_min_rating(result) < args.min_rating:
                skipped_rating += 1
                log.debug(f"[{replay_id}] rating too low: {result['ratings']}")
            else:
                # 保存
                out_path = out_dir / f"{replay_id}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
                saved += 1
                log.debug(f"[{replay_id}] saved (ratings={result['ratings']})")

            # レート制限対策
            time.sleep(random.uniform(args.delay_min, args.delay_max))

    log.info(f"完了: saved={saved}, skipped_low_rating={skipped_rating}, failed={failed}")


if __name__ == "__main__":
    main()
