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

### Component log (chains, tires, wheelsets, …)

Track swaps and wear per component. You only log *which* part went on
*which* bike (or parent component) and *when* — mileage is reconstructed
automatically from the activities table.

Components form a hierarchy: tires and cassettes mount on a **wheelset**,
wheelsets and chains mount on a **bike**. A component inherits miles from
whatever its parent is mounted on. Mileage is filtered by what actually
wears each part: `wheelset` / `tires` / `cassette` types skip VirtualRide
miles, and a `trainer`-type component (an indoor trainer modeled as a
wheelset) collects *only* VirtualRide miles — including for the cassette
mounted on it.

```bash
# Mount a component (creates it on first use via slug:type)
uv run strava-db component install chain-a:chain firefly

# Mount onto another component: tires on wheels, wheels on the bike
uv run strava-db component install gp5k:tires enve-45 --position rear
uv run strava-db component install enve-45:wheelset firefly

# The trainer is a wheelset: it moves between bikes, owns its cassette
uv run strava-db component install tacx-neo:trainer tarmac
uv run strava-db component install cass-10sp:cassette tacx-neo

# Swapping is implicit: installing a chain displaces the current chain
uv run strava-db component install chain-b:chain firefly

# Declare a bike's full setup (seed a new bike, or recover a missed swap)
uv run strava-db component state turbo nx-chain:chain pg1210:cassette \
    dt-g540:wheelset tracer-pro:tires --date 2026-07-08

# Log a wear measurement
uv run strava-db component measure chain-a 0.32 --notes "pre-wax"

# What's on each bike, with miles per install and lifetime
uv run strava-db component status

# One component's full install + measurement history
uv run strava-db component history chain-a
```

Bikes can be referenced by gear id (`b12345`) or any unique name
substring (`firefly`). Backdate any event with `--date YYYY-MM-DD`; use
`--position front` when two of the same type live on one bike.

---

## Common options

| Flag | Default | Description |
|---|---|---|
| `--db PATH` | `$DB_PATH` from `.env` | Override the SQLite file location |
| `--env PATH` | `.env` | Use a different env file |
| `--verify-days N` | `30` | Days to re-verify in `update` mode |

---

## Dashboard (GitHub Pages)

The dashboard lives at **[strava.andyreagan.com](https://strava.andyreagan.com)** — a single
self-contained `index.html` with all 9 000+ activities embedded as JSON.

To regenerate it after a DB update:

```bash
uv run strava-html               # reads strava.db, writes index.html
# or explicitly:
uv run python build_html.py --db strava.db --out index.html
```

Then commit and push — GitHub Pages serves it automatically from `main`.

```bash
git add index.html strava.db && git commit -m "Update dashboard" && git push
```

## Development

```bash
uv run ruff check strava_db.py build_html.py   # lint
uv run pytest                                   # tests (add to tests/ as needed)
```
