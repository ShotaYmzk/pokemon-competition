"""
Kaggle Environments episode API probe and downloader.

Examples:
    python datasets/fetch_kaggle_episodes.py --probe-only
    python datasets/fetch_kaggle_episodes.py --episode-id 12345678
    python datasets/fetch_kaggle_episodes.py --team-id 123456 --limit 5
    python datasets/fetch_kaggle_episodes.py --submission-id 123456 --limit 5
"""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

import requests
import kaggle_environments.api as kg_api
from kaggle_environments import (
    get_episode_replay,
    list_episodes,
    list_episodes_for_submission,
    list_episodes_for_team,
)


ENVIRONMENT = "pokemon-tcg-ai-battle"


def summarize(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, dict):
        summary["keys"] = list(value.keys())
        for key in ("id", "episodeId", "environment", "steps", "rewards", "statuses"):
            if key in value:
                item = value[key]
                summary[key] = f"list[{len(item)}]" if isinstance(item, list) else item
    elif isinstance(value, list):
        summary["len"] = len(value)
        if value:
            summary["first_type"] = type(value[0]).__name__
            summary["first"] = summarize(value[0])
    else:
        summary["preview"] = str(value)[:500]
    return summary


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def get_episode_id(episode: Any) -> int | None:
    if isinstance(episode, int):
        return episode
    if not isinstance(episode, dict):
        return None
    for key in ("id", "episodeId", "EpisodeId", "episode_id"):
        value = episode.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def probe_environment_listing() -> Any:
    try:
        return list_episodes(environment=ENVIRONMENT)  # type: ignore[call-arg]
    except TypeError as exc:
        return {
            "error": "list_episodes_environment_not_supported",
            "message": str(exc),
            "signature": str(inspect.signature(list_episodes)),
        }


def post_api_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, json=body, timeout=30)
    result: dict[str, Any] = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "url": response.url,
    }
    try:
        result["json"] = response.json()
    except ValueError:
        result["text_preview"] = response.text[:500]
    return result


def safe_list_episodes_for_team(team_id: int) -> Any:
    try:
        return list_episodes_for_team(team_id)
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "message": str(exc),
            "raw_response": post_api_json(kg_api.list_url, {"TeamId": team_id}),
        }


def safe_list_episodes_for_submission(submission_id: int) -> Any:
    try:
        return list_episodes_for_submission(submission_id)
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "message": str(exc),
            "raw_response": post_api_json(kg_api.list_url, {"SubmissionId": submission_id}),
        }


def safe_get_episode_replay(episode_id: int) -> Any:
    try:
        return get_episode_replay(episode_id)
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "message": str(exc),
            "raw_response": post_api_json(kg_api.get_url, {"EpisodeId": episode_id}),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Kaggle episode replays.")
    parser.add_argument("--team-id", type=int, help="Kaggle team ID for list_episodes_for_team")
    parser.add_argument(
        "--submission-id",
        type=int,
        help="Kaggle submission ID for list_episodes_for_submission",
    )
    parser.add_argument(
        "--episode-id",
        type=int,
        action="append",
        default=[],
        help="Episode ID to fetch. Can be passed multiple times.",
    )
    parser.add_argument("--limit", type=int, default=1, help="Replay fetch limit from team episodes")
    parser.add_argument("--out", type=str, default="datasets/kaggle_episodes", help="Output directory")
    parser.add_argument("--probe-only", action="store_true", help="Only print API capability summary")
    args = parser.parse_args()

    out_dir = Path(args.out)

    print("API signatures:")
    print(f"  list_episodes: {inspect.signature(list_episodes)}")
    print(f"  list_episodes_for_team: {inspect.signature(list_episodes_for_team)}")
    print(f"  list_episodes_for_submission: {inspect.signature(list_episodes_for_submission)}")
    print(f"  get_episode_replay: {inspect.signature(get_episode_replay)}")

    env_listing = probe_environment_listing()
    print("Environment listing probe:")
    print(json.dumps(summarize(env_listing), ensure_ascii=False, indent=2))

    if args.probe_only:
        return

    episode_ids = list(args.episode_id)

    if args.team_id is not None:
        episodes = safe_list_episodes_for_team(args.team_id)
        write_json(out_dir / f"team_{args.team_id}_episodes.json", episodes)
        print("Team episodes:")
        print(json.dumps(summarize(episodes), ensure_ascii=False, indent=2))

        for episode in episodes[: args.limit] if isinstance(episodes, list) else []:
            episode_id = get_episode_id(episode)
            if episode_id is not None and episode_id not in episode_ids:
                episode_ids.append(episode_id)

    if args.submission_id is not None:
        episodes = safe_list_episodes_for_submission(args.submission_id)
        write_json(out_dir / f"submission_{args.submission_id}_episodes.json", episodes)
        print("Submission episodes:")
        print(json.dumps(summarize(episodes), ensure_ascii=False, indent=2))

        for episode in episodes[: args.limit] if isinstance(episodes, list) else []:
            episode_id = get_episode_id(episode)
            if episode_id is not None and episode_id not in episode_ids:
                episode_ids.append(episode_id)

    if not episode_ids:
        print("No episode IDs available. Pass --episode-id, --team-id, or --submission-id.")
        return

    for episode_id in episode_ids[: args.limit]:
        replay = safe_get_episode_replay(episode_id)
        write_json(out_dir / "replays" / f"{episode_id}.json", replay)
        print(f"Replay {episode_id}:")
        print(json.dumps(summarize(replay), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
