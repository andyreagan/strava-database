#!/usr/bin/env python3
"""
build_html.py  –  Generate index.html from strava.db.

Usage:
    uv run python build_html.py           # reads strava.db, writes index.html
    uv run python build_html.py --db PATH --out PATH
"""

import argparse
import json
import sqlite3
from pathlib import Path


def load_data(db_path: str) -> tuple[list[dict], dict[str, str]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT
            a.id, a.name, a.sport_type,
            substr(a.start_date_local, 1, 10) AS date,
            ROUND(a.distance_m * 0.000621371, 2) AS miles,
            a.moving_time_s,
            ROUND(a.total_elevation_m * 3.28084, 0) AS elev_ft,
            a.average_heartrate,
            a.average_watts,
            COALESCE(g.name, a.gear_name, a.gear_id) AS gear,
            a.gear_id,
            a.commute,
            a.trainer,
            a.workout_type
        FROM activities a
        LEFT JOIN gear g ON g.id = a.gear_id
        ORDER BY a.start_date_local ASC
    """).fetchall()
    acts = [dict(r) for r in rows]

    bikes: dict[str, str] = {}
    for a in acts:
        gid = a.get("gear_id") or ""
        if gid.startswith("b") and a.get("gear"):
            bikes[gid] = a["gear"]

    return acts, bikes


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Andy's Strava Dashboard</title>
<style>
  /* ── reset / base ── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2a2d3a;
    --accent:   #fc4c02;   /* Strava orange */
    --accent2:  #f8961e;
    --text:     #e8eaf0;
    --muted:    #8b90a0;
    --good:     #43aa8b;
    --radius:   8px;
    --font:     'Inter', system-ui, sans-serif;
  }}
  body {{ font-family: var(--font); background: var(--bg); color: var(--text);
          font-size: 14px; line-height: 1.5; }}
  a {{ color: var(--accent); text-decoration: none; }}

  /* ── layout ── */
  header {{ background: var(--surface); border-bottom: 1px solid var(--border);
             padding: 12px 24px; display: flex; align-items: center; gap: 16px; }}
  header h1 {{ font-size: 1.2rem; font-weight: 700; color: var(--accent); }}
  header .subtitle {{ color: var(--muted); font-size: 0.85rem; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px 16px; }}

  /* ── filters ── */
  .filters {{ background: var(--surface); border: 1px solid var(--border);
               border-radius: var(--radius); padding: 16px; margin-bottom: 20px; }}
  .filters h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em;
                  color: var(--muted); margin-bottom: 12px; }}
  .filter-row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }}
  .filter-group {{ display: flex; flex-direction: column; gap: 4px; }}
  .filter-group label {{ font-size: 0.75rem; color: var(--muted); }}
  select, input[type=date], input[type=text] {{
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 6px 10px; font-size: 0.85rem;
    min-width: 130px; cursor: pointer;
  }}
  select:focus, input:focus {{ outline: 2px solid var(--accent); border-color: var(--accent); }}
  .btn {{ background: var(--accent); color: #fff; border: none; border-radius: 6px;
           padding: 7px 16px; cursor: pointer; font-size: 0.85rem; font-weight: 600; }}
  .btn:hover {{ background: var(--accent2); }}
  .btn.secondary {{ background: var(--surface); border: 1px solid var(--border);
                    color: var(--text); }}
  .btn.secondary:hover {{ border-color: var(--accent); color: var(--accent); }}

  /* ── summary cards ── */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
             gap: 12px; margin-bottom: 20px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 14px 16px; }}
  .card .label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: .06em;
                   color: var(--muted); margin-bottom: 4px; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; color: var(--text); }}
  .card .sub   {{ font-size: 0.75rem; color: var(--muted); margin-top: 2px; }}

  /* ── tabs ── */
  .tabs {{ display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 1px solid var(--border); }}
  .tab {{ padding: 8px 16px; cursor: pointer; border-radius: 6px 6px 0 0;
           font-size: 0.85rem; color: var(--muted); border: 1px solid transparent;
           border-bottom: none; margin-bottom: -1px; }}
  .tab.active {{ background: var(--surface); border-color: var(--border);
                  color: var(--text); font-weight: 600; }}
  .tab:hover:not(.active) {{ color: var(--text); }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}

  /* ── tables ── */
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  thead th {{ background: var(--surface); color: var(--muted); font-weight: 600;
               text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border);
               white-space: nowrap; cursor: pointer; user-select: none; }}
  thead th:hover {{ color: var(--text); }}
  thead th.sorted-asc::after  {{ content: ' ↑'; color: var(--accent); }}
  thead th.sorted-desc::after {{ content: ' ↓'; color: var(--accent); }}
  tbody tr {{ border-bottom: 1px solid var(--border); }}
  tbody tr:hover {{ background: var(--surface); }}
  tbody td {{ padding: 7px 10px; white-space: nowrap; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .badge {{ display: inline-block; padding: 1px 7px; border-radius: 99px;
             font-size: 0.7rem; font-weight: 600; background: var(--border); }}
  .badge.Run       {{ background: #2d4a3e; color: #43aa8b; }}
  .badge.Ride      {{ background: #3a2d1a; color: #f8961e; }}
  .badge.EBikeRide {{ background: #3a2d1a; color: #f8961e; }}
  .badge.VirtualRide {{ background: #3a2d1a; color: #f8961e; }}
  .badge.Walk      {{ background: #1e2a3a; color: #5fa8d3; }}
  .badge.Hike      {{ background: #2a1e3a; color: #9d77c9; }}
  .badge.Swim      {{ background: #1a2e3a; color: #48bfe3; }}
  .badge.commute   {{ background: #1a2e3a; color: #48bfe3; }}
  .badge.race      {{ background: #3a1a1a; color: var(--accent); }}

  /* ── charts ── */
  .chart-wrap {{ background: var(--surface); border: 1px solid var(--border);
                  border-radius: var(--radius); padding: 16px; margin-bottom: 20px;
                  overflow-x: auto; }}
  .chart-wrap h3 {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: .06em;
                     color: var(--muted); margin-bottom: 12px; }}
  .bar-chart {{ display: flex; align-items: flex-end; gap: 3px;
                 height: 140px; padding-bottom: 24px; position: relative; }}
  .bar-col {{ display: flex; flex-direction: column; align-items: center;
               gap: 0; flex: 1; min-width: 22px; max-width: 60px; height: 100%;
               justify-content: flex-end; position: relative; }}
  .bar {{ width: 100%; border-radius: 3px 3px 0 0; background: var(--accent);
           transition: opacity .15s; cursor: default; min-height: 2px; }}
  .bar:hover {{ opacity: 0.75; }}
  .bar-label {{ position: absolute; bottom: -20px; font-size: 0.6rem; color: var(--muted);
                 white-space: nowrap; text-align: center; width: 100%; }}
  .bar-val {{ position: absolute; top: -16px; font-size: 0.6rem; color: var(--muted);
               text-align: center; width: 100%; white-space: nowrap; }}

  /* ── gear table in bike tab ── */
  .gear-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
                   flex-wrap: wrap; }}

  /* ── pagination ── */
  .pagination {{ display: flex; gap: 6px; align-items: center; margin-top: 12px;
                  flex-wrap: wrap; }}
  .pagination button {{ background: var(--surface); border: 1px solid var(--border);
    color: var(--text); border-radius: 6px; padding: 4px 10px; cursor: pointer;
    font-size: 0.8rem; }}
  .pagination button:hover, .pagination button.active {{ border-color: var(--accent);
    color: var(--accent); }}
  .pagination .info {{ color: var(--muted); font-size: 0.8rem; }}

  /* ── misc ── */
  .empty {{ padding: 40px; text-align: center; color: var(--muted); }}
  @media (max-width: 600px) {{
    .filter-row {{ flex-direction: column; }}
    select, input {{ min-width: 100%; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>🏃 Strava Dashboard</h1>
    <div class="subtitle" id="header-sub">Loading…</div>
  </div>
</header>

<div class="container">

  <!-- ── FILTERS ── -->
  <div class="filters">
    <h2>Filters</h2>
    <div class="filter-row">
      <div class="filter-group">
        <label>Sport type</label>
        <select id="f-sport"><option value="">All sports</option></select>
      </div>
      <div class="filter-group">
        <label>Gear / bike</label>
        <select id="f-gear"><option value="">All gear</option></select>
      </div>
      <div class="filter-group">
        <label>Commute</label>
        <select id="f-commute">
          <option value="">Any</option>
          <option value="1">Commute only</option>
          <option value="0">Non-commute</option>
        </select>
      </div>
      <div class="filter-group">
        <label>From date</label>
        <input type="date" id="f-from">
      </div>
      <div class="filter-group">
        <label>To date</label>
        <input type="date" id="f-to">
      </div>
      <div class="filter-group">
        <label>Search name</label>
        <input type="text" id="f-search" placeholder="keyword…" style="min-width:160px">
      </div>
      <div class="filter-group" style="justify-content:flex-end">
        <button class="btn secondary" id="btn-reset">Reset</button>
      </div>
    </div>
  </div>

  <!-- ── SUMMARY CARDS ── -->
  <div class="cards" id="cards"></div>

  <!-- ── TABS ── -->
  <div class="tabs">
    <div class="tab active" data-tab="weekly">Weekly Volume</div>
    <div class="tab" data-tab="yearly">Yearly Totals</div>
    <div class="tab" data-tab="bikes">By Bike</div>
    <div class="tab" data-tab="activities">Activities</div>
  </div>

  <!-- ── WEEKLY PANEL ── -->
  <div class="panel active" id="panel-weekly">
    <div class="chart-wrap">
      <h3>Weekly miles — <span id="weekly-sport-label">all sports</span></h3>
      <div class="bar-chart" id="weekly-chart"></div>
    </div>
    <div class="table-wrap">
      <table id="weekly-table">
        <thead><tr>
          <th>Week</th><th class="num">Activities</th>
          <th class="num">Miles</th><th class="num">Time</th>
          <th class="num">Elev ft</th>
        </tr></thead>
        <tbody id="weekly-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- ── YEARLY PANEL ── -->
  <div class="panel" id="panel-yearly">
    <div class="chart-wrap">
      <h3>Annual miles by sport</h3>
      <div id="yearly-chart-wrap"></div>
    </div>
    <div class="table-wrap">
      <table id="yearly-table">
        <thead><tr>
          <th>Year</th><th>Sport</th>
          <th class="num">Activities</th><th class="num">Miles</th>
          <th class="num">Time</th><th class="num">Elev ft</th>
          <th class="num">Avg HR</th>
        </tr></thead>
        <tbody id="yearly-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- ── BIKES PANEL ── -->
  <div class="panel" id="panel-bikes">
    <div class="gear-header">
      <span style="color:var(--muted);font-size:0.8rem">Show from:</span>
      <input type="date" id="bike-from">
      <span style="color:var(--muted);font-size:0.8rem">to:</span>
      <input type="date" id="bike-to">
      <button class="btn secondary" id="bike-reset">All time</button>
    </div>
    <div class="table-wrap">
      <table id="bikes-table">
        <thead><tr>
          <th>Bike</th><th class="num">Rides</th>
          <th class="num">Miles</th><th class="num">Moving Time</th>
          <th class="num">Elev ft</th><th class="num">Commutes</th>
          <th class="num">Avg HR</th>
        </tr></thead>
        <tbody id="bikes-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- ── ACTIVITIES PANEL ── -->
  <div class="panel" id="panel-activities">
    <div class="table-wrap">
      <table id="act-table">
        <thead><tr>
          <th data-col="date">Date</th>
          <th data-col="name">Name</th>
          <th data-col="sport_type">Sport</th>
          <th data-col="miles" class="num">Miles</th>
          <th data-col="moving_time_s" class="num">Time</th>
          <th data-col="elev_ft" class="num">Elev ft</th>
          <th data-col="average_heartrate" class="num">Avg HR</th>
          <th data-col="average_watts" class="num">Watts</th>
          <th data-col="gear">Gear</th>
        </tr></thead>
        <tbody id="act-tbody"></tbody>
      </table>
    </div>
    <div class="pagination" id="act-pagination"></div>
  </div>

</div><!-- /container -->

<script>
// ── DATA ──────────────────────────────────────────────────────────────────
{data_js}

// ── HELPERS ───────────────────────────────────────────────────────────────
const fmtTime = s => {{
  if (!s) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h ? `${{h}}h ${{String(m).padStart(2,'0')}}m` : `${{m}}m`;
}};
const fmtMi = v => v == null ? '—' : v.toFixed(1);
const fmtN  = v => v == null ? '—' : Math.round(v).toLocaleString();
const fmtHR = v => v == null ? '—' : Math.round(v);

// ISO week string: "2024-W03"
const isoWeek = dateStr => {{
  const d = new Date(dateStr + 'T12:00:00');
  const jan4 = new Date(d.getFullYear(), 0, 4);
  const w = Math.ceil(((d - jan4) / 86400000 + jan4.getDay() + 1) / 7);
  const y = w === 0 ? d.getFullYear() - 1 : (w > 52 && d.getMonth() === 0 ? d.getFullYear() - 1 : d.getFullYear());
  return `${{y}}-W${{String(w).padStart(2,'0')}}`;
}};

const WORKOUT_LABELS = {{0:'Default',1:'Race',2:'Long Run',3:'Workout',
                          10:'Default',11:'Race',12:'Workout'}};

const SPORT_COLORS = {{
  Run:'#43aa8b', VirtualRun:'#43aa8b', Ride:'#f8961e', EBikeRide:'#f8961e',
  VirtualRide:'#f8961e', GravelRide:'#f8961e', MountainBikeRide:'#f8961e',
  Walk:'#5fa8d3', Hike:'#9d77c9', Swim:'#48bfe3',
  WeightTraining:'#e0aaff', Workout:'#e0aaff', Crossfit:'#e0aaff',
  NordicSki:'#caf0f8', AlpineSki:'#caf0f8',
}};
const sportColor = s => SPORT_COLORS[s] || '#8b90a0';

// ── STATE ─────────────────────────────────────────────────────────────────
let filtered = [...ALL_ACTIVITIES];
let actSortCol = 'date', actSortDir = -1; // -1 = desc
let actPage = 1;
const ACT_PAGE_SIZE = 50;

// Bike-panel date range (independent of global filters)
let bikeFrom = null, bikeTo = null;

// ── INIT FILTERS ──────────────────────────────────────────────────────────
const sportSel  = document.getElementById('f-sport');
const gearSel   = document.getElementById('f-gear');
const commuteSel= document.getElementById('f-commute');
const fromInput = document.getElementById('f-from');
const toInput   = document.getElementById('f-to');
const searchInput = document.getElementById('f-search');

SPORT_TYPES.forEach(s => {{
  const o = document.createElement('option'); o.value = s; o.textContent = s;
  sportSel.appendChild(o);
}});

// Gear dropdown: bikes + shoes separately
const gearOpts = Object.entries(BIKES).map(([id,name]) => ({{id,name,type:'bike'}}));
// Also collect shoe gear from data
const shoeMap = {{}};
ALL_ACTIVITIES.forEach(a => {{
  if (a.gear_id && !a.gear_id.startsWith('b') && a.gear)
    shoeMap[a.gear_id] = a.gear;
}});
// Group in select
const bgBike = document.createElement('optgroup'); bgBike.label = '🚲 Bikes';
gearOpts.forEach(({{id,name}}) => {{
  const o = document.createElement('option'); o.value = id; o.textContent = name;
  bgBike.appendChild(o);
}});
gearSel.appendChild(bgBike);
const bgShoe = document.createElement('optgroup'); bgShoe.label = '👟 Shoes';
Object.entries(shoeMap).forEach(([id,name]) => {{
  const o = document.createElement('option'); o.value = id; o.textContent = name;
  bgShoe.appendChild(o);
}});
gearSel.appendChild(bgShoe);

[sportSel, gearSel, commuteSel, fromInput, toInput].forEach(el =>
  el.addEventListener('change', applyFilters));
searchInput.addEventListener('input', applyFilters);
document.getElementById('btn-reset').addEventListener('click', resetFilters);

// ── FILTER LOGIC ──────────────────────────────────────────────────────────
function applyFilters() {{
  const sport   = sportSel.value;
  const gear    = gearSel.value;
  const commute = commuteSel.value;
  const from    = fromInput.value;
  const to      = toInput.value;
  const search  = searchInput.value.toLowerCase();

  filtered = ALL_ACTIVITIES.filter(a => {{
    if (sport   && a.sport_type !== sport) return false;
    if (gear    && a.gear_id    !== gear)  return false;
    if (commute !== '' && String(a.commute) !== commute) return false;
    if (from    && a.date < from) return false;
    if (to      && a.date > to)   return false;
    if (search  && !(a.name || '').toLowerCase().includes(search)) return false;
    return true;
  }});
  actPage = 1;
  render();
}}

function resetFilters() {{
  sportSel.value = ''; gearSel.value = ''; commuteSel.value = '';
  fromInput.value = ''; toInput.value = ''; searchInput.value = '';
  filtered = [...ALL_ACTIVITIES];
  actPage = 1;
  render();
}}

// ── RENDER ────────────────────────────────────────────────────────────────
function render() {{
  renderCards();
  renderWeekly();
  renderYearly();
  renderBikes();
  renderActivities();
}}

// ── CARDS ─────────────────────────────────────────────────────────────────
function renderCards() {{
  const n     = filtered.length;
  const miles = filtered.reduce((s,a) => s + (a.miles||0), 0);
  const secs  = filtered.reduce((s,a) => s + (a.moving_time_s||0), 0);
  const elev  = filtered.reduce((s,a) => s + (a.elev_ft||0), 0);
  const hrs   = filtered.filter(a=>a.average_heartrate).map(a=>a.average_heartrate);
  const avgHR = hrs.length ? hrs.reduce((s,v)=>s+v,0)/hrs.length : null;

  // Date range
  const dates = filtered.map(a=>a.date).filter(Boolean).sort();
  const span  = dates.length ? `${{dates[0]}} → ${{dates[dates.length-1]}}` : '—';

  document.getElementById('header-sub').textContent =
    `${{n.toLocaleString()}} activities · ${{span}}`;

  const defs = [
    ['Activities', n.toLocaleString(),         ''],
    ['Miles',      miles.toFixed(1),            ''],
    ['Moving time',fmtTime(secs),               ''],
    ['Elev gain',  fmtN(elev) + ' ft',         ''],
    ['Avg HR',     avgHR ? fmtHR(avgHR)+' bpm':'—', ''],
    ['Runs',       filtered.filter(a=>a.sport_type==='Run'||a.sport_type==='VirtualRun').length,''],
    ['Rides',      filtered.filter(a=>a.sport_type&&a.sport_type.includes('Ride')).length,''],
    ['Commutes',   filtered.filter(a=>a.commute).length,''],
  ];
  const el = document.getElementById('cards');
  el.innerHTML = defs.map(([lbl,val,sub]) =>
    `<div class="card"><div class="label">${{lbl}}</div>
     <div class="value">${{val}}</div>
     ${{sub ? `<div class="sub">${{sub}}</div>` : ''}}</div>`
  ).join('');
}}

// ── WEEKLY ────────────────────────────────────────────────────────────────
function renderWeekly() {{
  // Group by ISO week
  const weeks = {{}};
  filtered.forEach(a => {{
    if (!a.date) return;
    const w = isoWeek(a.date);
    if (!weeks[w]) weeks[w] = {{acts:0, miles:0, secs:0, elev:0}};
    weeks[w].acts++;
    weeks[w].miles += a.miles||0;
    weeks[w].secs  += a.moving_time_s||0;
    weeks[w].elev  += a.elev_ft||0;
  }});
  const keys = Object.keys(weeks).sort();

  // Chart: last 52 weeks (or all if fewer)
  const chartKeys = keys.slice(-52);
  const maxMi = Math.max(...chartKeys.map(k => weeks[k].miles), 1);
  const chartEl = document.getElementById('weekly-chart');
  chartEl.innerHTML = chartKeys.map(k => {{
    const pct = (weeks[k].miles / maxMi * 100).toFixed(1);
    const shortLabel = k.slice(5); // "W03"
    return `<div class="bar-col" title="${{k}}: ${{weeks[k].miles.toFixed(1)}} mi">
      <div class="bar-val">${{weeks[k].miles >= maxMi*0.6 ? weeks[k].miles.toFixed(0) : ''}}</div>
      <div class="bar" style="height:${{pct}}%"></div>
      <div class="bar-label">${{shortLabel}}</div>
    </div>`;
  }}).join('');

  // Table: all weeks, newest first
  const tbody = document.getElementById('weekly-tbody');
  tbody.innerHTML = [...keys].reverse().map(k => {{
    const w = weeks[k];
    return `<tr>
      <td>${{k}}</td>
      <td class="num">${{w.acts}}</td>
      <td class="num">${{w.miles.toFixed(1)}}</td>
      <td class="num">${{fmtTime(w.secs)}}</td>
      <td class="num">${{fmtN(w.elev)}}</td>
    </tr>`;
  }}).join('');

  const sportLabel = sportSel.value || 'all sports';
  document.getElementById('weekly-sport-label').textContent = sportLabel;
}}

// ── YEARLY ────────────────────────────────────────────────────────────────
function renderYearly() {{
  // Group by year × sport
  const data = {{}};
  filtered.forEach(a => {{
    if (!a.date) return;
    const y = a.date.slice(0,4);
    const s = a.sport_type || 'Unknown';
    const key = `${{y}}|${{s}}`;
    if (!data[key]) data[key] = {{year:y, sport:s, acts:0, miles:0, secs:0, elev:0, hrSum:0, hrN:0}};
    data[key].acts++;
    data[key].miles += a.miles||0;
    data[key].secs  += a.moving_time_s||0;
    data[key].elev  += a.elev_ft||0;
    if (a.average_heartrate) {{ data[key].hrSum += a.average_heartrate; data[key].hrN++; }}
  }});

  // Per-year totals for chart
  const yearTotals = {{}};
  Object.values(data).forEach(d => {{
    if (!yearTotals[d.year]) yearTotals[d.year] = {{}};
    yearTotals[d.year][d.sport] = (yearTotals[d.year][d.sport]||0) + d.miles;
  }});
  const years = Object.keys(yearTotals).sort();

  // Stacked bar chart by top sports
  const topSports = Object.entries(
    filtered.reduce((acc,a) => {{ acc[a.sport_type||'?']=(acc[a.sport_type||'?']||0)+(a.miles||0); return acc; }},{{}})
  ).sort((a,b)=>b[1]-a[1]).slice(0,6).map(e=>e[0]);

  const maxYearMi = Math.max(...years.map(y =>
    Object.values(yearTotals[y]).reduce((s,v)=>s+v,0)), 1);

  const chartWrap = document.getElementById('yearly-chart-wrap');
  const bars = years.map(y => {{
    const total = Object.values(yearTotals[y]).reduce((s,v)=>s+v,0);
    const pct = total / maxYearMi * 100;
    const segments = topSports.map(s => {{
      const mi = yearTotals[y][s]||0;
      const h = mi / maxYearMi * 100;
      return `<div style="height:${{h.toFixed(1)}}%;background:${{sportColor(s)}};width:100%;border-radius:0" title="${{s}}: ${{mi.toFixed(0)}} mi"></div>`;
    }}).join('');
    return `<div class="bar-col" style="max-width:80px" title="${{y}}: ${{total.toFixed(0)}} mi">
      <div class="bar-val">${{total.toFixed(0)}}</div>
      <div style="height:${{pct.toFixed(1)}}%;width:100%;display:flex;flex-direction:column-reverse;border-radius:3px 3px 0 0;overflow:hidden">${{segments}}</div>
      <div class="bar-label">${{y}}</div>
    </div>`;
  }}).join('');

  // Legend
  const legend = topSports.map(s =>
    `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:.75rem">
      <span style="width:10px;height:10px;border-radius:2px;background:${{sportColor(s)}};display:inline-block"></span>${{s}}
    </span>`).join('');

  chartWrap.innerHTML = `
    <div style="margin-bottom:8px">${{legend}}</div>
    <div class="bar-chart" style="height:180px">${{bars}}</div>`;

  // Table
  const rows = Object.values(data).sort((a,b) =>
    b.year.localeCompare(a.year) || b.miles - a.miles);
  const tbody = document.getElementById('yearly-tbody');
  tbody.innerHTML = rows.map(d => `<tr>
    <td>${{d.year}}</td>
    <td><span class="badge ${{d.sport}}">${{d.sport}}</span></td>
    <td class="num">${{d.acts}}</td>
    <td class="num">${{d.miles.toFixed(1)}}</td>
    <td class="num">${{fmtTime(d.secs)}}</td>
    <td class="num">${{fmtN(d.elev)}}</td>
    <td class="num">${{d.hrN ? fmtHR(d.hrSum/d.hrN) : '—'}}</td>
  </tr>`).join('');
}}

// ── BIKES ─────────────────────────────────────────────────────────────────
function renderBikes() {{
  const fromVal = bikeFrom || (document.getElementById('bike-from').value||null);
  const toVal   = bikeTo   || (document.getElementById('bike-to').value||null);

  // Use global filters PLUS bike date overrides
  let src = filtered.filter(a => a.gear_id && a.gear_id.startsWith('b'));
  if (fromVal) src = src.filter(a => a.date >= fromVal);
  if (toVal)   src = src.filter(a => a.date <= toVal);

  const gear = {{}};
  src.forEach(a => {{
    const key = a.gear_id;
    if (!gear[key]) gear[key] = {{name: a.gear||key, rides:0, miles:0, secs:0, elev:0, hrSum:0, hrN:0, commutes:0}};
    gear[key].rides++;
    gear[key].miles   += a.miles||0;
    gear[key].secs    += a.moving_time_s||0;
    gear[key].elev    += a.elev_ft||0;
    gear[key].commutes+= a.commute||0;
    if (a.average_heartrate) {{ gear[key].hrSum += a.average_heartrate; gear[key].hrN++; }}
  }});

  const rows = Object.values(gear).sort((a,b) => b.miles - a.miles);
  const tbody = document.getElementById('bikes-tbody');
  if (!rows.length) {{
    tbody.innerHTML = `<tr><td colspan="7" class="empty">No ride data matches current filters.</td></tr>`;
    return;
  }}
  tbody.innerHTML = rows.map(g => `<tr>
    <td><strong>${{g.name}}</strong></td>
    <td class="num">${{g.rides}}</td>
    <td class="num">${{g.miles.toFixed(1)}}</td>
    <td class="num">${{fmtTime(g.secs)}}</td>
    <td class="num">${{fmtN(g.elev)}}</td>
    <td class="num">${{g.commutes}}</td>
    <td class="num">${{g.hrN ? fmtHR(g.hrSum/g.hrN) : '—'}}</td>
  </tr>`).join('');
}}

// Bike date pickers (independent of global filters)
document.getElementById('bike-from').addEventListener('change', e => {{ bikeFrom = e.target.value||null; renderBikes(); }});
document.getElementById('bike-to').addEventListener('change',   e => {{ bikeTo   = e.target.value||null; renderBikes(); }});
document.getElementById('bike-reset').addEventListener('click', () => {{
  bikeFrom = bikeTo = null;
  document.getElementById('bike-from').value = '';
  document.getElementById('bike-to').value = '';
  renderBikes();
}});

// ── ACTIVITIES TABLE ──────────────────────────────────────────────────────
function renderActivities() {{
  // Sort
  const mul = actSortDir;
  const sorted = [...filtered].sort((a,b) => {{
    const av = a[actSortCol], bv = b[actSortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    return av < bv ? -mul : av > bv ? mul : 0;
  }});

  // Pagination
  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total / ACT_PAGE_SIZE));
  actPage = Math.min(actPage, pages);
  const slice = sorted.slice((actPage-1)*ACT_PAGE_SIZE, actPage*ACT_PAGE_SIZE);

  // Update sort indicators
  document.querySelectorAll('#act-table thead th[data-col]').forEach(th => {{
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.dataset.col === actSortCol)
      th.classList.add(actSortDir === 1 ? 'sorted-asc' : 'sorted-desc');
  }});

  const tbody = document.getElementById('act-tbody');
  tbody.innerHTML = slice.map(a => {{
    const wl = a.workout_type != null ? WORKOUT_LABELS[a.workout_type] : null;
    const badge = wl && wl !== 'Default'
      ? `<span class="badge race" style="margin-left:4px">${{wl}}</span>` : '';
    const commBadge = a.commute ? `<span class="badge commute" style="margin-left:4px">commute</span>` : '';
    const link = `<a href="https://www.strava.com/activities/${{a.id}}" target="_blank" title="Open on Strava">↗</a>`;
    return `<tr>
      <td>${{a.date}}</td>
      <td>${{link}} ${{a.name||'—'}}${{badge}}${{commBadge}}</td>
      <td><span class="badge ${{a.sport_type}}">${{a.sport_type||'—'}}</span></td>
      <td class="num">${{fmtMi(a.miles)}}</td>
      <td class="num">${{fmtTime(a.moving_time_s)}}</td>
      <td class="num">${{fmtN(a.elev_ft)}}</td>
      <td class="num">${{fmtHR(a.average_heartrate)}}</td>
      <td class="num">${{a.average_watts != null ? Math.round(a.average_watts) : '—'}}</td>
      <td>${{a.gear||'—'}}</td>
    </tr>`;
  }}).join('');

  // Pagination controls
  const pg = document.getElementById('act-pagination');
  if (pages <= 1) {{ pg.innerHTML=''; return; }}
  const buttons = [];
  buttons.push(`<span class="info">Page ${{actPage}} of ${{pages}} (${{total.toLocaleString()}} activities)</span>`);
  if (actPage > 1)  buttons.push(`<button onclick="setPage(${{actPage-1}})">‹ Prev</button>`);
  // window of page buttons
  const lo = Math.max(1, actPage-3), hi = Math.min(pages, actPage+3);
  for (let p = lo; p <= hi; p++)
    buttons.push(`<button class="${{p===actPage?'active':''}}" onclick="setPage(${{p}})">${{p}}</button>`);
  if (actPage < pages) buttons.push(`<button onclick="setPage(${{actPage+1}})">Next ›</button>`);
  pg.innerHTML = buttons.join('');
}}

window.setPage = p => {{ actPage = p; renderActivities(); window.scrollTo(0,0); }};

// Sort by column header click
document.querySelectorAll('#act-table thead th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    if (actSortCol === th.dataset.col) actSortDir *= -1;
    else {{ actSortCol = th.dataset.col; actSortDir = -1; }}
    actPage = 1;
    renderActivities();
  }});
}});

// ── TABS ──────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
  }});
}});

// ── BOOT ──────────────────────────────────────────────────────────────────
render();
</script>
</body>
</html>
"""


def build(db_path: str, out_path: str) -> None:
    print(f"Loading data from {db_path} …")
    acts, bikes = load_data(db_path)

    sport_types = sorted({a["sport_type"] for a in acts if a["sport_type"]})

    data_js = (
        f"const ALL_ACTIVITIES = {json.dumps(acts, separators=(',', ':'))};\n"
        f"const BIKES = {json.dumps(bikes)};\n"
        f"const SPORT_TYPES = {json.dumps(sport_types)};\n"
    )

    html = HTML_TEMPLATE.format(data_js=data_js)
    Path(out_path).write_text(html, encoding="utf-8")
    size = Path(out_path).stat().st_size
    print(f"Written {out_path} ({size/1024/1024:.2f} MB, {len(acts)} activities)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate index.html from strava.db")
    ap.add_argument("--db",  default="strava.db",   help="SQLite DB path")
    ap.add_argument("--out", default="index.html",  help="Output HTML path")
    args = ap.parse_args()
    build(args.db, args.out)


if __name__ == "__main__":
    main()
