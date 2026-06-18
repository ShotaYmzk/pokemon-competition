"""
Probe replay endpoints with Kaggle browser cookies plus an optional API token.

The token is read from KAGGLE_API_TOKEN or /tmp/kaggle/access_token. The token is
not written to repository files.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import requests


EPISODE_ID = 80408508
COMPETITION_URL = "https://www.kaggle.com/competitions/pokemon-tcg-ai-battle"
OUT_PATH = pathlib.Path("datasets/kaggle_episodes/auth_replay_probe_80408508.json")


def read_token() -> str | None:
    token = os.environ.get("KAGGLE_API_TOKEN")
    if token:
        return token.strip()
    token_file = pathlib.Path("/tmp/kaggle/access_token")
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    return None


def make_headers(session: requests.Session) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/html,*/*",
        "Content-Type": "application/json",
    }
    xsrf = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
    if xsrf:
        headers["X-XSRF-TOKEN"] = xsrf
    token = read_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def body_prefix(response: requests.Response) -> str:
    text = response.text[:500]
    return text.replace(read_token() or "", "[REDACTED]")


def main() -> None:
    session = requests.Session()
    landing = session.get(COMPETITION_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    headers = make_headers(session)
    print("competition page", landing.status_code)
    print("has token", bool(read_token()))
    print("has xsrf", "X-XSRF-TOKEN" in headers)

    probes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("POST", "https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay", {"episodeId": EPISODE_ID}),
        ("POST", "https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisode", {"episodeId": EPISODE_ID}),
        ("POST", "https://www.kaggle.com/api/i/kernel.EpisodeService/GetEpisodeReplay", {"episodeId": EPISODE_ID}),
        ("GET", f"https://www.kaggle.com/api/v1/episodes/{EPISODE_ID}/replay", None),
        ("GET", f"https://www.kaggle.com/api/v1/episodes/{EPISODE_ID}", None),
        ("POST", "https://www.kaggle.com/requests/EpisodeService/GetEpisodeReplay", {"EpisodeId": EPISODE_ID}),
    ]

    results = []
    for method, url, body in probes:
        if method == "POST":
            response = session.post(url, headers=headers, json=body, timeout=30)
        else:
            response = session.get(url, headers=headers, timeout=30)
        result = {
            "method": method,
            "url": url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "body_prefix": body_prefix(response),
        }
        print(f"\n{method} {url}")
        print("status:", result["status"])
        print("content-type:", result["content_type"])
        print("body[:500]:", result["body_prefix"])
        try:
            payload = response.json()
            result["json_keys"] = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
            if response.status_code == 200:
                out = pathlib.Path(f"datasets/kaggle_episodes/replays/auth_{EPISODE_ID}_{len(results)}.json")
                out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                result["saved_json"] = str(out)
        except ValueError:
            pass
        results.append(result)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved", OUT_PATH)


if __name__ == "__main__":
    main()
