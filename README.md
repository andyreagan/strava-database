# strava-database

A local SQLite metadata database of your Strava activities, with a CLI to build
and keep it up-to-date.  Useful for calculating things like miles per bike,
commute stats, weekly run mileage, and weekly workout time.

## Setup

### 1 — Prerequisites

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) then:

```bash
uv sync          # creates .venv and installs all dependencies
```

### 2 — Credentials

```bash
cp .env.example .env
```

Fill in `.env` with your Strava API credentials from
<https://www.strava.com/settings/api>:

| Variable | Description |
|---|---|
| `STRAVA_CLIENT_ID` | Numeric app ID |
| `STRAVA_CLIENT_SECRET` | App secret |
| `STRAVA_ACCESS_TOKEN` | Initial access token (auto-refreshed) |
| `STRAVA_REFRESH_TOKEN` | Refresh token (updated in-place) |
| `DB_PATH` | SQLite file path (default: `strava.db`) |

> **Scope**: the app needs at least `activity:read_all` in its Strava settings.

---

## Usage

All commands are run via `uv run strava-db <mode>` (or `uv run python strava_db.py <mode>`).

### Build from a Strava archive export (fastest)

Download your data at <https://www.strava.com/athlete/delete_your_account>
(scroll to *Download or Delete Your Account* → *Request Your Archive*).

```bash
uv run strava-db build-archive ~/Downloads/export_12345.zip
```

### Build from the API (no archive needed)

Pulls everything page-by-page, sleeping automatically to respect Strava's
100 req / 15 min rate limit.  A large history may take 30–60 min.

```bash
uv run strava-db build-api
```

### Incremental update (run on a schedule / cron)

Fetches only activities newer than the most-recent row in the DB, then
re-fetches and verifies the last 30 days (configurable).

```bash
uv run strava-db update

# Re-verify 60 days instead of the default 30
uv run strava-db update --verify-days 60
```

### Quick stats report

```bash
uv run strava-db stats
```

Prints:

- Total activities and date range
- Breakdown by sport type (count, miles, moving time)
- **Miles per bike** (gear) with commute count
- **Weekly run mileage** (last 12 weeks)
- **Weekly workout time** (all types, last 12 weeks)
- **Commute rides** by year

---

## Common options

| Flag | Default | Description |
|---|---|---|
| `--db PATH` | `$DB_PATH` from `.env` | Override the SQLite file location |
| `--env PATH` | `.env` | Use a different env file |
| `--verify-days N` | `30` | Days to re-verify in `update` mode |

---

## Development

```bash
uv run ruff check strava_db.py   # lint
uv run pytest                    # tests (add to tests/ as needed)
```
