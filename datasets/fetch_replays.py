"""
Fetch Kaggle episode replay JSON for pokemon-tcg-ai-battle.

The episode IDs are read from datasets/kaggle_episodes/valid_episode_ids.json.
This script first probes one episode across known replay endpoints, prints the
structure of the first successful response, then fetches the remaining episodes
with a one-second delay.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Any

import requests


COMPETITION_URL = "https://www.kaggle.com/competitions/pokemon-tcg-ai-battle"
VALID_IDS_PATH = pathlib.Path("datasets/kaggle_episodes/valid_episode_ids.json")
OUT_DIR = pathlib.Path("datasets/kaggle_episodes/replays")

ENDPOINTS = [
    ("POST", "https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay", {"episodeId": None}),
    ("POST", "https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisode", {"episodeId": None}),
    ("GET", "https://www.kaggle.com/api/v1/episodes/{episode_id}/replay", None),
    ("POST", "https://www.kaggle.com/api/i/kernel.EpisodeService/GetEpisodeReplay", {"episodeId": None}),
]


def load_episode_ids(path: pathlib.Path) -> list[int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    ids: list[int] = []

    def add(value: Any) -> None:
        if isinstance(value, int):
            ids.append(value)
        elif isinstance(value, str) and value.isdigit():
            ids.append(int(value))

    if isinstance(raw, list):
        for value in raw:
            add(value)
    elif isinstance(raw, dict):
        for item in raw.values():
            if isinstance(item, dict):
                for value in item.get("episode_ids", []):
                    add(value)
            else:
                add(item)

    return sorted(set(ids), reverse=True)


def make_session() -> tuple[requests.Session, dict[str, str]]:
    session = requests.Session()
    session.get(COMPETITION_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    token = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers["X-XSRF-TOKEN"] = token
    return session, headers


def request_endpoint(
    session: requests.Session,
    headers: dict[str, str],
    endpoint: tuple[str, str, dict[str, Any] | None],
    episode_id: int,
) -> requests.Response:
    method, url, body_template = endpoint
    if method == "GET":
        return session.get(url.format(episode_id=episode_id), headers=headers, timeout=30)

    body = dict(body_template or {})
    for key, value in list(body.items()):
        if value is None and key.lower().endswith("id"):
            body[key] = episode_id
    return session.post(url, headers=headers, json=body, timeout=30)


def fetch_json(
    session: requests.Session,
    headers: dict[str, str],
    endpoint: tuple[str, str, dict[str, Any] | None],
    episode_id: int,
) -> Any | None:
    response = request_endpoint(session, headers, endpoint, episode_id)
    print(f"episode {episode_id}: {endpoint[0]} {endpoint[1]} status={response.status_code}")
    print("content-type:", response.headers.get("content-type"))
    print("body[:500]:", response.text[:500])
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def is_replay_like(data: Any) -> bool:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return any(key in data[0] for key in ("action", "select", "selected", "obs", "current", "logs"))
    if isinstance(data, dict):
        for key in ("replayData", "replay_data", "steps"):
            value = data.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return any(step_key in value[0] for step_key in ("action", "select", "selected", "obs", "current", "logs"))
    return False


def save_replay(episode_id: int, data: Any) -> pathlib.Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{episode_id}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def print_structure(data: Any) -> None:
    print("=== top-level keys ===")
    if isinstance(data, dict):
        print(list(data.keys()))
        for key, value in data.items():
            print(f"{key}: {type(value).__name__}, ", end="")
            if isinstance(value, list):
                print(f"len={len(value)}")
            elif isinstance(value, str):
                print(repr(value[:100]))
            else:
                print(str(value)[:100])
    elif isinstance(data, list):
        print(f"list, len={len(data)}")
        if data:
            step0 = data[0]
            print("\n=== step0 keys ===", list(step0.keys()) if isinstance(step0, dict) else type(step0))
            if isinstance(step0, dict):
                for key in ["action", "select", "selected", "ps", "obs"]:
                    print(f"\n--- {key} ---")
                    print(json.dumps(step0.get(key), ensure_ascii=False)[:300])
    else:
        print(type(data).__name__)


def main() -> None:
    episode_ids = load_episode_ids(VALID_IDS_PATH)
    if not episode_ids:
        raise SystemExit(f"No episode IDs found in {VALID_IDS_PATH}")

    session, headers = make_session()

    first_id = episode_ids[0]
    successful_endpoint = None
    first_data = None
    fallback_endpoint = None
    fallback_data = None
    for endpoint in ENDPOINTS:
        data = fetch_json(session, headers, endpoint, first_id)
        if data is None:
            continue
        if fallback_endpoint is None:
            fallback_endpoint = endpoint
            fallback_data = data
        if is_replay_like(data):
            successful_endpoint = endpoint
            first_data = data
            break

    if successful_endpoint is None or first_data is None:
        if fallback_endpoint is None or fallback_data is None:
            raise SystemExit("No endpoint returned JSON.")
        print("No replay-like endpoint succeeded; saving first JSON response for inspection.")
        successful_endpoint = fallback_endpoint
        first_data = fallback_data

    first_path = save_replay(first_id, first_data)
    print("saved", first_path)
    print_structure(first_data)

    fetched = 1
    for episode_id in episode_ids[1:10]:
        time.sleep(1)
        data = fetch_json(session, headers, successful_endpoint, episode_id)
        if data is None:
            continue
        path = save_replay(episode_id, data)
        print("saved", path)
        fetched += 1

    print("successful_endpoint", successful_endpoint[1])
    print("fetched", fetched)


if __name__ == "__main__":
    main()
