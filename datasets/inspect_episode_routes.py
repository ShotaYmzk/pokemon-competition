"""
Inspect episode metadata and probe possible replay routes.
"""

from __future__ import annotations

import json
import pathlib
import re

import requests


EPISODE_ID = 80408508
METADATA_PATH = pathlib.Path(f"datasets/kaggle_episodes/replays/{EPISODE_ID}.json")


def inspect_metadata() -> dict:
    data = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    ep = data.get("episode", {})
    print("=== episode keys ===")
    for key, value in ep.items():
        print(f"  {key}: {repr(value)[:200]}")

    teams = data.get("teams", [])
    print(f"\n=== teams (count={len(teams)}) ===")
    for team in teams:
        print(json.dumps(team, ensure_ascii=False)[:300])

    return data


def probe_heroz() -> dict:
    url = f"https://ptcgvis.heroz.jp/Visualizer/Replay/{EPISODE_ID}/0"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    match = re.search(r"var replayData = (.{0,200})", response.text)
    snippet = match.group(0) if match else "not found"
    print("\n=== HEROZ ===")
    print("url:", url)
    print("status:", response.status_code)
    print("replayData snippet:", snippet)
    return {
        "url": url,
        "status": response.status_code,
        "snippet": snippet,
        "has_nonempty_replay_data": "var replayData = [" in response.text,
    }


def probe_kaggle_routes() -> list[dict]:
    session = requests.Session()
    session.get(
        "https://www.kaggle.com/competitions/pokemon-tcg-ai-battle",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    token = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/html,*/*",
        "Content-Type": "application/json",
    }
    if token:
        headers["X-XSRF-TOKEN"] = token

    probes = [
        ("GET", "https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/simulations", None),
        (
            "GET",
            f"https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodeAgents?episodeId={EPISODE_ID}",
            None,
        ),
        (
            "GET",
            f"https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay?episodeId={EPISODE_ID}",
            None,
        ),
        (
            "POST",
            "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodeAgents",
            {"episodeId": EPISODE_ID},
        ),
        (
            "POST",
            "https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay",
            {"episodeId": EPISODE_ID},
        ),
    ]

    results = []
    print("\n=== Kaggle routes ===")
    for method, url, body in probes:
        if method == "POST":
            response = session.post(url, headers=headers, json=body, timeout=30)
        else:
            response = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        print(f"\n{method} {url}")
        print("  status:", response.status_code)
        print("  content-type:", response.headers.get("content-type"))
        print("  body[:300]:", response.text[:300])
        results.append(
            {
                "method": method,
                "url": url,
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "body_prefix": response.text[:300],
            }
        )
    return results


def main() -> None:
    data = inspect_metadata()
    hero = probe_heroz()
    kaggle = probe_kaggle_routes()

    out = pathlib.Path("datasets/kaggle_episodes/route_probe_80408508.json")
    out.write_text(
        json.dumps(
            {
                "episode_keys": list(data.get("episode", {}).keys()),
                "team_keys": [list(team.keys()) for team in data.get("teams", [])],
                "heroz": hero,
                "kaggle": kaggle,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nsaved", out)


if __name__ == "__main__":
    main()
