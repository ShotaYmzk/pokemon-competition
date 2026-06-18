"""
Find valid Kaggle episode IDs for pokemon-tcg-ai-battle.

This script does not fetch replay bodies. It only discovers episode IDs by:
1. Opening the public competition page to get Kaggle cookies.
2. Calling the internal leaderboard API to get submission IDs.
3. Passing submission IDs to kaggle_environments.list_episodes_for_submission().
4. Falling back to the current internal EpisodeService/ListEpisodes endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
from kaggle_environments import list_episodes_for_submission


COMPETITION_NAME = "pokemon-tcg-ai-battle"
COMPETITION_URL = f"https://www.kaggle.com/competitions/{COMPETITION_NAME}"
GET_COMPETITION_URL = "https://www.kaggle.com/api/i/competitions.CompetitionService/GetCompetition"
GET_LEADERBOARD_URL = "https://www.kaggle.com/api/i/competitions.LeaderboardService/GetLeaderboard"
LIST_EPISODES_URL = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
OUT_DIR = Path("datasets/kaggle_episodes")


def headers(session: requests.Session) -> dict[str, str]:
    h = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
    if token:
        h["X-XSRF-TOKEN"] = token
    return h


def post_json(session: requests.Session, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = session.post(url, headers=headers(session), json=body, timeout=30)
    print(url.rsplit("/", 1)[-1], response.status_code, response.text[:2000])
    response.raise_for_status()
    return response.json()


def try_official_list_episodes_for_submission(submission_id: int) -> Any:
    try:
        return list_episodes_for_submission(submission_id)
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


def normalize_episode_ids(payload: Any) -> list[int]:
    if isinstance(payload, dict):
        episodes = payload.get("episodes", [])
    elif isinstance(payload, list):
        episodes = payload
    else:
        episodes = []

    ids: list[int] = []
    for episode in episodes:
        if isinstance(episode, dict):
            value = episode.get("id") or episode.get("episodeId") or episode.get("EpisodeId")
        else:
            value = episode
        if isinstance(value, int):
            ids.append(value)
        elif isinstance(value, str) and value.isdigit():
            ids.append(int(value))
    return ids


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    page = session.get(COMPETITION_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    print("competition page", page.status_code, page.url)

    competition = post_json(session, GET_COMPETITION_URL, {"competitionName": COMPETITION_NAME})
    competition_id = competition["id"]
    print("competition_id", competition_id)

    leaderboard = post_json(session, GET_LEADERBOARD_URL, {"competitionId": competition_id})
    (OUT_DIR / "leaderboard.json").write_text(
        json.dumps(leaderboard, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    public_rows = leaderboard.get("publicLeaderboard", [])
    submission_ids = [
        row["submissionId"]
        for row in public_rows
        if isinstance(row, dict) and isinstance(row.get("submissionId"), int)
    ]
    print("submission_ids", submission_ids[:20])

    found: dict[int, dict[str, Any]] = {}
    for submission_id in submission_ids[:20]:
        official = try_official_list_episodes_for_submission(submission_id)
        fallback = post_json(session, LIST_EPISODES_URL, {"submissionId": submission_id})
        ids = normalize_episode_ids(fallback) or normalize_episode_ids(official)
        found[submission_id] = {
            "official": official,
            "fallback": fallback,
            "episode_ids": ids,
        }
        print("submission", submission_id, "episode_ids", ids[:10])
        if ids:
            break

    out = OUT_DIR / "valid_episode_ids.json"
    out.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    all_ids = sorted({episode_id for item in found.values() for episode_id in item["episode_ids"]})
    print("valid_episode_ids", all_ids[:50])
    print("saved", out)


if __name__ == "__main__":
    main()
