# Claude memories

Human-readable notes that Claude Code keeps about this project and its owner.
Claude reads this file at the start of a session and updates it in place when
something new and non-obvious is learned. Edit freely; keep it short.

## Bike fleet

Strava gear ids are the ones in `strava.db`.

- **Turbo** (b18306489): Specialized Turbo Creo 2 Comp ebike, bought
  2026-07-08. Commuter, ~52 mi round trip (25.9 each way). SRAM Apex/X1
  **Eagle** mullet (standard Eagle 12sp chain, NOT Flattop). Specs in
  `~/brain/specializedturbolevo.org` (filename is a misnomer). Front Pelago
  Commuter rack (Large) + strapped Ortlieb backpack for laptop. No wax on this
  bike; drip lube.
  - Payoff goal: "pay off" $7k at $1/mi vs driving (~26 full commute weeks).
  - Mileage goal set 2026-09-08: 3,000 mi on the Turbo by end of 2026 (was
    1,136 mi then). Plan is 3 commute days/wk, skipping Thanksgiving and
    Christmas weeks plus ~5 other days.
- **Firefly 1169** (b11215203): custom Ti race/gravel bike, Classified
  Powershift hub, SRAM Force/Rival AXS. Three YBN SLA1210 chains
  (bronze/silver/gold) in hot-wax rotation since 2025-01; second Classified
  cassette since 2025-03-25. Two wheelsets swapped ad hoc: Classified carbon
  gravel (RH tires) and ENVE 4.5 road (fall 2025; Pirelli rear after
  2026-03-29 blowout). Maintenance log: `~/brain/firefly1169.org`.
- **Mean Machine** (b422150): TT bike, 10sp, new KMC chain 2026-05-21.
- **Tarmac** (b2860836): on the Tacx Neo trainer (10sp cassette on trainer).
- **Epic** (b17607154): Specialized Epic EVO MTB, bone stock.
- **Commueter** (b779434, sic): the DIY "fast" ebike, e-bike rides since
  Dec 2017. Did the ~26-mi-each-way Springfield commute Aug 2025 to May 2026
  (fastest of the fleet, ~25 mph AM) before the Creo replaced it.

The Springfield commute (~26 mi each way, AM out ~7-8a, PM home ~4-5p)
started 2025-08-05. Ridden on Commueter (Aug 2025 to May 2026), Firefly
(Mar to Jun 2026, pedal-only), Turbo Creo (Jul 2026 onward).

Habits: measures chain wear with KMC digital checker + digital caliper;
hot-waxes only the Firefly. Component swaps/measurements are logged via
`strava-db component ...` (built 2026-07-24).

## Where bike history lives

Per-bike org notes in `~/brain` (beyond the obvious names): `kazane.org`,
`raleighfurley.org` (= Commueter), `tarmacSL3.org`, `wheeltop.org`,
`niner.org`, `classified.org` (Firefly hub), `metrofiets.org`,
`moonlander.org` (= Larry), `cannondale.org`, `tacxneo2t.org`,
`trainerroad.org`, `velocirack-5x.org`, plus `firefly1169.org`,
`ebikes.org`, `specializedturbolevo.org` (= Creo).

Ride titles are a reliable maintenance log ("New wheel day", "First ride on
the studs", "Ebike motor and battery now on the mountain bike!"); grep them
when reconstructing history. The structured results of the 2026-07-28
archaeology session are seeded in `strava.db` tables `components` and
`component_installs`; open questions are in `QUESTIONS.md`.

## Working preferences

- Keep Claude's memories in this file, not only in the hidden per-user
  memory directory, so they are readable and versioned with the repo.
- After a `strava-db update`, rebuild `index.html` with `build_html.py` and
  commit both together.
