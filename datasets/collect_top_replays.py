"""Collect public replay JSON files from top leaderboard teams.

This script shells out to the Kaggle CLI because the public replay download path
is already handled there:

    ./bin/kaggle competitions replay <episode_id>

It discovers top teams, their public submissions, and public episodes, then
downloads replay JSON files into datasets/top_replays/replays/.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


COMPETITION = "pokemon-tcg-ai-battle"
DEFAULT_OUT_DIR = Path("datasets/top_replays")


@dataclass
class TeamRow:
    team_id: int
    team_name: str
    submission_date: str
    score: str


@dataclass
class SubmissionRow:
    team_id: int
    submission_id: int
    date_submitted: str
    public_score: str


@dataclass
class EpisodeRow:
    team_id: int
    submission_id: int
    episode_id: int
    create_time: str
    end_time: str
    state: str
    episode_type: str


def run_kaggle(kaggle_bin: str, args: list[str], dry_run: bool = False) -> str:
    cmd = [kaggle_bin, *args]
    if dry_run:
        print("DRY-RUN", " ".join(cmd))
        return ""
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return completed.stdout
    except subprocess.CalledProcessError as exc:
        output = exc.stdout or ""
        raise RuntimeError(
            f"Kaggle command failed with exit code {exc.returncode}: {' '.join(cmd)}\n{output}"
        ) from exc


def parse_leaderboard(text: str, limit: int) -> list[TeamRow]:
    rows: list[TeamRow] = []
    pattern = re.compile(
        r"^\s*(?P<team_id>\d+)\s+"
        r"(?P<team_name>.*?)\s{2,}"
        r"(?P<date>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
        r"(?P<score>\S+)\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        rows.append(
            TeamRow(
                team_id=int(match.group("team_id")),
                team_name=match.group("team_name").strip(),
                submission_date=match.group("date"),
                score=match.group("score"),
            )
        )
        if len(rows) >= limit:
            break
    return rows


def parse_team_submissions(text: str, team_id: int) -> list[SubmissionRow]:
    rows: list[SubmissionRow] = []
    pattern = re.compile(
        r"^\s*(?P<submission_id>\d+)\s+"
        r"(?P<date>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
        r"(?P<score>\S+)\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        rows.append(
            SubmissionRow(
                team_id=team_id,
                submission_id=int(match.group("submission_id")),
                date_submitted=match.group("date"),
                public_score=match.group("score"),
            )
        )
    return rows


def parse_episodes(text: str, team_id: int, submission_id: int) -> list[EpisodeRow]:
    rows: list[EpisodeRow] = []
    pattern = re.compile(
        r"^\s*(?P<episode_id>\d+)\s+"
        r"(?P<create>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
        r"(?P<end>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
        r"(?P<state>\S+)\s+"
        r"(?P<type>\S+)\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        rows.append(
            EpisodeRow(
                team_id=team_id,
                submission_id=submission_id,
                episode_id=int(match.group("episode_id")),
                create_time=match.group("create"),
                end_time=match.group("end"),
                state=match.group("state"),
                episode_type=match.group("type"),
            )
        )
    return rows


def iter_selected_episodes(
    episodes: Iterable[EpisodeRow],
    episodes_per_submission: int,
) -> Iterable[EpisodeRow]:
    selected = 0
    for episode in episodes:
        if "COMPLETED" not in episode.state:
            continue
        yield episode
        selected += 1
        if selected >= episodes_per_submission:
            return


def download_replay(
    kaggle_bin: str,
    episode: EpisodeRow,
    out_dir: Path,
    dry_run: bool,
    overwrite: bool,
) -> Path | None:
    replay_dir = out_dir / "replays"
    replay_dir.mkdir(parents=True, exist_ok=True)
    target = replay_dir / f"{episode.episode_id}.json"
    if target.exists() and not overwrite:
        print("skip existing", target)
        return target

    if dry_run:
        print("DRY-RUN replay", episode.episode_id, "->", target)
        return None

    before = set(Path.cwd().glob(f"episode-{episode.episode_id}-replay.json"))
    run_kaggle(kaggle_bin, ["competitions", "replay", str(episode.episode_id)])
    downloaded = Path(f"episode-{episode.episode_id}-replay.json")
    if not downloaded.exists() and not before:
        raise RuntimeError(f"Kaggle CLI did not produce {downloaded}")
    if downloaded.resolve() != target.resolve():
        if target.exists():
            target.unlink()
        shutil.move(str(downloaded), target)
    return target


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def default_kaggle_bin() -> str:
    local = Path("bin/kaggle")
    if local.exists():
        return "./bin/kaggle"
    return "kaggle"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kaggle-bin", default=default_kaggle_bin())
    parser.add_argument("--competition", default=COMPETITION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-teams", type=int, default=20)
    parser.add_argument("--submissions-per-team", type=int, default=1)
    parser.add_argument("--episodes-per-submission", type=int, default=5)
    parser.add_argument("--max-replays", type=int, default=50)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    leaderboard_text = run_kaggle(
        args.kaggle_bin,
        ["competitions", "leaderboard", args.competition, "-s"],
        dry_run=args.dry_run,
    )
    teams = parse_leaderboard(leaderboard_text, args.top_teams) if leaderboard_text else []
    write_json(args.out_dir / "leaderboard_rows.json", [asdict(row) for row in teams])
    print("teams", len(teams))

    submissions: list[SubmissionRow] = []
    episodes: list[EpisodeRow] = []
    downloaded: list[dict[str, object]] = []

    for team in teams:
        text = run_kaggle(
            args.kaggle_bin,
            ["competitions", "team-submissions", str(team.team_id)],
            dry_run=args.dry_run,
        )
        team_submissions = parse_team_submissions(text, team.team_id)[: args.submissions_per_team]
        submissions.extend(team_submissions)

        for submission in team_submissions:
            text = run_kaggle(
                args.kaggle_bin,
                ["competitions", "episodes", str(submission.submission_id)],
                dry_run=args.dry_run,
            )
            submission_episodes = parse_episodes(text, team.team_id, submission.submission_id)
            episodes.extend(submission_episodes)

            for episode in iter_selected_episodes(submission_episodes, args.episodes_per_submission):
                if len(downloaded) >= args.max_replays:
                    break
                path = download_replay(
                    args.kaggle_bin,
                    episode,
                    args.out_dir,
                    dry_run=args.dry_run,
                    overwrite=args.overwrite,
                )
                downloaded.append(
                    {
                        **asdict(episode),
                        "team_name": team.team_name,
                        "score": team.score,
                        "path": str(path) if path is not None else None,
                    }
                )
            if len(downloaded) >= args.max_replays:
                break
        if len(downloaded) >= args.max_replays:
            break

    write_json(args.out_dir / "submission_rows.json", [asdict(row) for row in submissions])
    write_json(args.out_dir / "episode_rows.json", [asdict(row) for row in episodes])
    write_json(args.out_dir / "downloaded_replays.json", downloaded)
    print("submissions", len(submissions))
    print("episodes", len(episodes))
    print("downloaded", len(downloaded))
    print("saved", args.out_dir)


if __name__ == "__main__":
    main()
