# Kaggle Episode Replay Findings

## 2026-06-18

### Episode ID discovery

- `datasets/find_valid_episode_ids.py` discovered episode IDs from Kaggle's current internal APIs.
- Working discovery path:
  - `GET https://www.kaggle.com/competitions/pokemon-tcg-ai-battle`
  - `POST https://www.kaggle.com/api/i/competitions.CompetitionService/GetCompetition`
    - body: `{"competitionName": "pokemon-tcg-ai-battle"}`
    - returned `competitionId = 116727`
  - `POST https://www.kaggle.com/api/i/competitions.LeaderboardService/GetLeaderboard`
    - body: `{"competitionId": 116727}`
    - returned public leaderboard rows with `submissionId`
  - `POST https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes`
    - body: `{"submissionId": <submission_id>}`
    - returned public episode metadata with `id`

### Replay fetch attempt

- `datasets/fetch_replays.py` tried the requested replay endpoints for episode `80408508`.
- Results:
  - `POST https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay`: `404`, HTML response
  - `GET https://www.kaggle.com/api/v1/episodes/80408508/replay`: `404`, HTML response
  - `POST https://www.kaggle.com/api/i/kernel.EpisodeService/GetEpisodeReplay`: `404`, HTML response
  - `POST https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisode`: `200`, JSON response

### Authentication

- No `kaggle.json` was available in this environment.
- The working internal APIs used anonymous browser-style Cookie/XSRF auth:
  - Start a `requests.Session()`
  - `GET https://www.kaggle.com/competitions/pokemon-tcg-ai-battle`
  - Read `XSRF-TOKEN` or `CSRF-TOKEN` from session cookies
  - Send `X-XSRF-TOKEN` with JSON POST requests

### Structure

- `GetEpisode` returns metadata, not replay steps.
- Top-level keys saved for each episode:
  - `episode`
  - `teams`
- `episode` contains IDs, timestamps, state, agents, scores, team IDs, and seed.
- It does not contain replayData-compatible step records.

ReplayData compatibility:

- `action`: absent
- `current`: absent
- `logs`: absent
- `obs`: absent
- `select`: absent
- `selected`: absent
- `ps`: absent

Conclusion:

- The saved files under `datasets/kaggle_episodes/replays/*.json` are episode metadata JSON, not the full replay body.
- They do not match the handoff document replayData structure.
- Step count is not available from these responses (`0` replay steps present).
- `selected` is not available and cannot be used as a behavioral cloning label from this endpoint.

## 2026-06-18 Route Probe

### Episode metadata keys

For `datasets/kaggle_episodes/replays/80408508.json`, top-level keys are:

- `episode`
- `teams`

`episode` keys:

- `id`
- `createTime`
- `endTime`
- `state`
- `type`
- `agents`
- `seed`

No direct replay fields were present:

- `url`: absent
- `replayUrl`: absent
- `visualizerUrl`: absent
- `renderUrl`: absent
- `steps`: absent
- `replayData`: absent

`episode.agents` includes:

- agent `id`
- `submissionId`
- `reward`
- `initialScore`
- `updatedScore`
- `teamId`
- `index` for the second agent

`teams` includes team metadata such as:

- `id`
- `teamName`
- `competitionId`
- `teamLeaderId`
- `submissionCount`
- `lastSubmissionDate`
- `publicLeaderboardSubmissionId`
- `publicLeaderboardScoreFormatted`
- `teamMembers`

### HEROZ visualizer check

Checked `https://ptcgvis.heroz.jp/Visualizer/Replay/80408508/0`.

- `GET`: returned `400`; no `replayData` snippet found.
- `POST`: returned `200`, but the body contained `var replayData = ;`.
- `var replayData = [` was not present.

Conclusion: HEROZ does not accept the Kaggle `episode.id` as a self-contained replay source. It is still behaving like a renderer that expects replay data to be supplied by the caller.

### Kaggle simulations/API checks

Checked:

- `GET https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/simulations`
- `GET https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodeAgents?episodeId=80408508`
- `GET https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay?episodeId=80408508`
- `POST https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodeAgents`
- `POST https://www.kaggle.com/api/i/competitions.EpisodeService/GetEpisodeReplay`

Results:

- The simulations page returned normal Kaggle HTML, but it did not contain `80408508`, `episode`, `replay`, `Visualizer`, or `EpisodeService` strings.
- No replay links or episode IDs were embedded in the simulations HTML.
- `ListEpisodeAgents` returned `404`.
- `GetEpisodeReplay` returned `404`.
- `GetEpisode` remains the only confirmed `200` endpoint, and it returns metadata only.

Probe output was saved to:

- `datasets/kaggle_episodes/route_probe_80408508.json`

### Current conclusion

The public anonymous Cookie/XSRF internal APIs expose leaderboard rows, submission IDs, episode IDs, and episode metadata. They do not expose the replay step body through the tested endpoints.

The replay body path is still unresolved. The next route to try is an authenticated browser session with a real Kaggle account, then inspect browser network traffic from the Simulations UI while opening a specific episode. If no additional request appears there, a separate Kaggle-side storage/API path or competition-specific frontend hook is needed.
