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
from datetime import date
from pathlib import Path

import streams as streams_mod


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


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-site="strava">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="ar-repo" content="strava-database">
<meta name="ar-generated" content="{generated}">
<title>Andy's Strava Dashboard</title>
<link rel="stylesheet" href="ar.css">
<style>
/* page-local: only what the kit lacks */
a { text-decoration: none; }
a.act-name { color: var(--text); }
a.act-name:hover { color: var(--accent); text-decoration: underline; }
.filters select { max-width: 180px; }
.filters .btn { padding: 6px 12px; }
.badge.sport::before { content: ''; display: inline-block; width: 7px; height: 7px;
                       border-radius: 50%; background: var(--c, var(--gray)); margin-right: 5px; }
.badge.flag { color: var(--accent); }
td .badge + .badge, td a + .badge { margin-left: 4px; }
.metric-card + .metric-card { margin-top: 16px; }
.wk-hl { fill: var(--text); opacity: .07; pointer-events: none; }
#cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 700px) { #cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 800px) {
  .filters .field { flex: 1 1 130px; }
  .filters select, .filters input { max-width: none; width: 100%; }
}
</style>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script src="ar.js"></script>
</head>
<body>

<!-- SIDEBAR -->
<nav class="sidebar">
  <div class="sidebar-logo">Andy's <span>Strava</span></div>

  <div class="nav-section">
    <div class="nav-section-title">Volume</div>
    <div class="nav-item active" data-section="weekly">
      <span class="icon">📊</span> Weekly Volume
    </div>
    <div class="nav-item" data-section="yearly">
      <span class="icon">📅</span> Yearly Totals
    </div>
  </div>

  <div class="nav-section">
    <div class="nav-section-title">Gear</div>
    <div class="nav-item" data-section="bikes">
      <span class="icon">🚲</span> By Bike
    </div>
  </div>

  <div class="nav-section">
    <div class="nav-section-title">Log</div>
    <div class="nav-item" data-section="activities">
      <span class="icon">📋</span> Activities
    </div>
  </div>
</nav>

<!-- MAIN -->
<div class="main">
  <div class="topbar">
    <div>
      <h1 id="section-title">Weekly Volume</h1>
      <div class="subtitle" id="header-sub">Loading…</div>
    </div>
    <div class="range-btns" id="range-btns">
      <button class="range-btn" data-days="84">12w</button>
      <button class="range-btn" data-days="365">1yr</button>
      <button class="range-btn" data-days="730">2yr</button>
      <button class="range-btn" data-days="1825">5yr</button>
      <button class="range-btn" data-days="0">All</button>
    </div>
  </div>

  <div class="content">

    <!-- ── FILTERS (scope everything below) ── -->
    <div class="filters">
      <div class="field">
        <label for="f-sport">Sport type</label>
        <select id="f-sport"><option value="">All sports</option></select>
      </div>
      <div class="field">
        <label for="f-gear">Gear / bike</label>
        <select id="f-gear"><option value="">All gear</option></select>
      </div>
      <div class="field">
        <label for="f-commute">Commute</label>
        <select id="f-commute">
          <option value="">Any</option>
          <option value="1">Commute only</option>
          <option value="0">Non-commute</option>
        </select>
      </div>
      <div class="field">
        <label for="f-from">From date</label>
        <input type="date" id="f-from">
      </div>
      <div class="field">
        <label for="f-to">To date</label>
        <input type="date" id="f-to">
      </div>
      <div class="field">
        <label for="f-search">Search name</label>
        <input type="text" id="f-search" placeholder="keyword…">
      </div>
      <div class="field">
        <button class="btn" id="btn-reset">Reset</button>
      </div>
    </div>

    <!-- ── SUMMARY ── -->
    <div class="kpi-strip" id="cards"></div>

    <!-- ── WEEKLY ── -->
    <div class="section active" id="section-weekly">
      <div class="metric-card">
        <div class="metric-card-header">
          <div>
            <div class="metric-card-title">Weekly <span class="metric-word">miles</span> — <span id="weekly-sport-label">all sports</span></div>
            <div class="metric-card-val" id="weekly-val" style="color:var(--accent)">—</div>
            <div class="metric-card-sub" id="weekly-sub"></div>
          </div>
          <div class="roll-btns metric-btns"></div>
        </div>
        <div id="weekly-legend"></div>
        <div class="chart-area" id="weekly-chart"></div>
      </div>
      <div class="metric-card">
        <div class="table-wrap">
          <table id="weekly-table">
            <thead><tr>
              <th>Week of</th><th class="num">Activities</th>
              <th class="num">Miles</th><th class="num">Time</th>
              <th class="num">Elev ft</th>
            </tr></thead>
            <tbody id="weekly-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── YEARLY ── -->
    <div class="section" id="section-yearly">
      <div class="metric-card">
        <div class="metric-card-header">
          <div class="metric-card-title">Annual <span class="metric-word">miles</span> by sport</div>
          <div class="roll-btns metric-btns"></div>
        </div>
        <div id="yearly-legend" style="margin-top:8px"></div>
        <div class="chart-area" id="yearly-chart"></div>
      </div>
      <div class="metric-card">
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
    </div>

    <!-- ── BIKES ── -->
    <div class="section" id="section-bikes">
      <div class="filters">
        <div class="field">
          <label for="bike-from">Show from</label>
          <input type="date" id="bike-from">
        </div>
        <div class="field">
          <label for="bike-to">to</label>
          <input type="date" id="bike-to">
        </div>
        <div class="field">
          <button class="btn" id="bike-reset">All time</button>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-card-header">
          <div class="metric-card-title"><span class="metric-word cap">Miles</span> by bike</div>
          <div class="roll-btns metric-btns"></div>
        </div>
        <div class="chart-area" id="bikes-chart" style="margin-top:8px"></div>
      </div>
      <div class="metric-card">
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
    </div>

    <!-- ── ACTIVITIES ── -->
    <div class="section" id="section-activities">
      <div class="metric-card">
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
    </div>

  </div><!-- /content -->
</div><!-- /main -->

<script>
// ── DATA ──────────────────────────────────────────────────────────────────
{data_js}

// ── HELPERS ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const fmtTime = s => {
  if (!s) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m`;
};
const fmtMi = v => v == null ? '—' : v.toFixed(1);
const fmtN  = v => v == null ? '—' : Math.round(v).toLocaleString();
const fmtHR = v => v == null ? '—' : Math.round(v);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
const isoDay = d3.timeFormat('%Y-%m-%d');
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

const WORKOUT_LABELS = {0:'Default',1:'Race',2:'Long Run',3:'Workout',
                        10:'Default',11:'Race',12:'Workout'};

// sport → kit series colour (identity); anything unlisted is gray
const SPORT_VARS = {
  Ride: 'accent', Run: 'blue', EBikeRide: 'yellow', VirtualRide: 'pink',
  Walk: 'teal', VirtualRun: 'purple', Hike: 'green', TrailRun: 'teal',
  GravelRide: 'red', MountainBikeRide: 'green', Swim: 'blue',
};
const sportColor = s => `var(--${SPORT_VARS[s] || 'gray'})`;
const sportBadge = s => `<span class="badge sport" style="--c:${sportColor(s)}">${esc(s || '—')}</span>`;

// weekly chart stacks three sport groups
const GROUPS = [
  { key: 'Ride',  name: 'Rides', color: 'var(--accent)' },
  { key: 'Run',   name: 'Runs',  color: 'var(--blue)' },
  { key: 'Other', name: 'Other', color: 'var(--gray)' },
];
const groupOf = s => /Ride/.test(s || '') ? 'Ride' : /Run/.test(s || '') ? 'Run' : 'Other';

// the metric the three charts plot (tables always show all of them)
const METRICS = {
  miles: { btn: 'Miles',   word: 'miles',          unit: 'mi', get: a => a.miles || 0,
           fmt: v => v.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1}) },
  hours: { btn: 'Hours',   word: 'hours',          unit: 'h',  get: a => (a.moving_time_s || 0) / 3600,
           fmt: v => v.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1}) },
  elev:  { btn: 'Elev ft', word: 'elevation gain', unit: 'ft', get: a => a.elev_ft || 0,
           fmt: v => Math.round(v).toLocaleString() },
};
let metric = 'miles';
const axisFmt = v => d3.format(',')(v);

// week = Monday-start, keyed by the Monday's date
ALL_ACTIVITIES.forEach(a => {
  a._wk  = a.date ? isoDay(d3.timeMonday.floor(AR.parseDate(a.date))) : null;
  a._grp = groupOf(a.sport_type);
});
const ALL_DATES = ALL_ACTIVITIES.map(a => a.date).filter(Boolean).sort();
const FIRST_DATE = ALL_DATES[0] || null, LAST_DATE = ALL_DATES[ALL_DATES.length - 1] || null;

// Draw now and again whenever the container's width changes (same idea as
// the kit's chart helpers, for the hand-written weekly chart).
function mount(el, height, draw) {
  if (el._ro) el._ro.disconnect();
  let lastW = -1;
  const run = () => {
    const w = Math.round(el.clientWidth);
    if (w === lastW) return;
    lastW = w;
    el.innerHTML = '';
    if (!w) return;
    const svg = d3.select(el).append('svg').attr('class', 'ar-chart')
      .attr('viewBox', `0 0 ${w} ${height}`).attr('height', height);
    draw(svg, w, height);
  };
  run();
  el._ro = new ResizeObserver(run);
  el._ro.observe(el);
}

// ── STATE ─────────────────────────────────────────────────────────────────
let filtered = [...ALL_ACTIVITIES];
let actSortCol = 'date', actSortDir = -1; // -1 = desc
let actPage = 1;
const ACT_PAGE_SIZE = 50;
const DEFAULT_RANGE_DAYS = 365;

// Bike-panel date range (independent of global filters)
let bikeFrom = null, bikeTo = null;

// ── INIT FILTERS ──────────────────────────────────────────────────────────
const sportSel  = $('f-sport');
const gearSel   = $('f-gear');
const commuteSel= $('f-commute');
const fromInput = $('f-from');
const toInput   = $('f-to');
const searchInput = $('f-search');

SPORT_TYPES.forEach(s => {
  const o = document.createElement('option'); o.value = s; o.textContent = s;
  sportSel.appendChild(o);
});

// Gear dropdown: bikes + shoes separately
const gearOpts = Object.entries(BIKES).map(([id,name]) => ({id,name,type:'bike'}));
const shoeMap = {};
ALL_ACTIVITIES.forEach(a => {
  if (a.gear_id && !a.gear_id.startsWith('b') && a.gear)
    shoeMap[a.gear_id] = a.gear;
});
const bgBike = document.createElement('optgroup'); bgBike.label = '🚲 Bikes';
gearOpts.forEach(({id,name}) => {
  const o = document.createElement('option'); o.value = id; o.textContent = name;
  bgBike.appendChild(o);
});
gearSel.appendChild(bgBike);
const bgShoe = document.createElement('optgroup'); bgShoe.label = '👟 Shoes';
Object.entries(shoeMap).forEach(([id,name]) => {
  const o = document.createElement('option'); o.value = id; o.textContent = name;
  bgShoe.appendChild(o);
});
gearSel.appendChild(bgShoe);

[sportSel, gearSel, commuteSel, fromInput, toInput].forEach(el =>
  el.addEventListener('change', applyFilters));
searchInput.addEventListener('input', applyFilters);
$('btn-reset').addEventListener('click', resetFilters);

// ── RANGE BUTTONS ─────────────────────────────────────────────────────────
// Presets for the From/To date filter, counted back from the latest activity
// and snapped to a Monday so the first weekly bar is a whole week.
function rangeFrom(days) {
  if (!days || !LAST_DATE) return '';
  return isoDay(d3.timeMonday.floor(d3.timeDay.offset(AR.parseDate(LAST_DATE), -days)));
}
function syncRangeBtns() {
  document.querySelectorAll('.range-btn').forEach(b => {
    b.classList.toggle('active', !toInput.value && fromInput.value === rangeFrom(+b.dataset.days));
  });
}
function setRange(days) {
  fromInput.value = rangeFrom(days);
  toInput.value = '';
  applyFilters();
}
document.querySelectorAll('.range-btn').forEach(b =>
  b.addEventListener('click', () => setRange(+b.dataset.days)));

// ── FILTER LOGIC ──────────────────────────────────────────────────────────
function applyFilters() {
  const sport   = sportSel.value;
  const gear    = gearSel.value;
  const commute = commuteSel.value;
  const from    = fromInput.value;
  const to      = toInput.value;
  const search  = searchInput.value.toLowerCase();

  filtered = ALL_ACTIVITIES.filter(a => {
    if (sport   && a.sport_type !== sport) return false;
    if (gear    && a.gear_id    !== gear)  return false;
    if (commute !== '' && String(a.commute) !== commute) return false;
    if (from    && a.date < from) return false;
    if (to      && a.date > to)   return false;
    if (search  && !(a.name || '').toLowerCase().includes(search)) return false;
    return true;
  });
  actPage = 1;
  syncRangeBtns();
  render();
}

function resetFilters() {
  sportSel.value = ''; gearSel.value = ''; commuteSel.value = '';
  searchInput.value = '';
  setRange(DEFAULT_RANGE_DAYS);
}

// ── RENDER ────────────────────────────────────────────────────────────────
function render() {
  document.querySelectorAll('.metric-btns').forEach(el => {
    el.innerHTML = Object.entries(METRICS).map(([k, m]) =>
      `<button class="roll-btn${k === metric ? ' active' : ''}" data-metric="${k}">${m.btn}</button>`).join('');
  });
  document.querySelectorAll('.metric-word').forEach(el => {
    const w = METRICS[metric].word;
    el.textContent = el.classList.contains('cap') ? w[0].toUpperCase() + w.slice(1) : w;
  });
  renderCards();
  renderWeekly();
  renderYearly();
  renderBikes();
  renderActivities();
}
document.addEventListener('click', e => {
  const b = e.target.closest('.roll-btn[data-metric]');
  if (!b) return;
  metric = b.dataset.metric;
  render();
});

// ── CARDS ─────────────────────────────────────────────────────────────────
function renderCards() {
  const n     = filtered.length;
  const miles = filtered.reduce((s,a) => s + (a.miles||0), 0);
  const secs  = filtered.reduce((s,a) => s + (a.moving_time_s||0), 0);
  const elev  = filtered.reduce((s,a) => s + (a.elev_ft||0), 0);
  const hrs   = filtered.filter(a=>a.average_heartrate).map(a=>a.average_heartrate);
  const avgHR = hrs.length ? hrs.reduce((s,v)=>s+v,0)/hrs.length : null;

  // Date range
  const dates = filtered.map(a=>a.date).filter(Boolean).sort();
  const span  = dates.length ? `${dates[0]} → ${dates[dates.length-1]}` : '—';

  $('header-sub').textContent = `${n.toLocaleString()} activities · ${span}`;

  const defs = [
    ['Activities', n.toLocaleString(),                'gray'],
    ['Miles',      miles.toLocaleString(undefined, {minimumFractionDigits:1, maximumFractionDigits:1}), 'accent'],
    ['Moving time',fmtTime(secs),                     'purple'],
    ['Elev gain',  fmtN(elev) + ' ft',                'green'],
    ['Avg HR',     avgHR ? fmtHR(avgHR)+' bpm':'—',   'red'],
    ['Runs',       filtered.filter(a=>a.sport_type==='Run'||a.sport_type==='VirtualRun').length.toLocaleString(), 'blue'],
    ['Rides',      filtered.filter(a=>a.sport_type&&a.sport_type.includes('Ride')).length.toLocaleString(), 'accent'],
    ['Commutes',   filtered.filter(a=>a.commute).length.toLocaleString(), 'yellow'],
  ];
  $('cards').innerHTML = defs.map(([lbl,val,cls]) =>
    `<div class="kpi-card" style="--kpi-color:var(--${cls})">
       <div class="kpi-label">${lbl}</div>
       <div class="kpi-value">${val}</div>
     </div>`
  ).join('');
}

// ── WEEKLY ────────────────────────────────────────────────────────────────
function renderWeekly() {
  const M = METRICS[metric];
  // Group by week (Monday start)
  const weeks = new Map();
  filtered.forEach(a => {
    if (!a._wk) return;
    let w = weeks.get(a._wk);
    if (!w) { w = {acts:0, miles:0, secs:0, elev:0, val:0, g:{Ride:0, Run:0, Other:0}}; weeks.set(a._wk, w); }
    w.acts++;
    w.miles += a.miles||0;
    w.secs  += a.moving_time_s||0;
    w.elev  += a.elev_ft||0;
    const v = M.get(a);
    w.val += v; w.g[a._grp] += v;
  });
  const keys = [...weeks.keys()].sort();

  $('weekly-sport-label').textContent = sportSel.value || 'all sports';

  // Chart window: every week (empty ones included) from the From filter, or
  // the first week with data, through the To filter / latest activity.
  const mon = s => d3.timeMonday.floor(AR.parseDate(s));
  let slots = [];
  if (keys.length) {
    const from = fromInput.value && fromInput.value > FIRST_DATE ? fromInput.value : null;
    const start = from ? mon(from) : AR.parseDate(keys[0]);
    let end = toInput.value && toInput.value < LAST_DATE ? mon(toInput.value)
            : from ? mon(LAST_DATE) : AR.parseDate(keys[keys.length - 1]);
    if (end < start) end = start;
    slots = d3.timeMonday.range(start, d3.timeDay.offset(end, 1));
  }
  const rows = slots.map(d => ({ d, w: weeks.get(isoDay(d)) || null }));

  // headline: average per week over the window, plus the biggest week
  const total = d3.sum(rows, r => r.w ? r.w.val : 0);
  const peak = d3.greatest(rows, r => r.w ? r.w.val : 0);
  $('weekly-val').textContent = rows.length ? `${M.fmt(total / rows.length)} ${M.unit}/week` : '—';
  $('weekly-sub').textContent = rows.length && peak && peak.w
    ? `average over ${rows.length.toLocaleString()} weeks · biggest ${M.fmt(peak.w.val)} ${M.unit}, week of ${AR.fmtDate(peak.d)}`
    : '';

  const used = GROUPS.filter(g => rows.some(r => r.w && r.w.g[g.key] > 0));
  const legendEl = $('weekly-legend');
  if (used.length > 1) AR.legend(legendEl, used); else legendEl.innerHTML = '';

  mount($('weekly-chart'), 260, (svg, W, H) => drawWeekly(svg, W, H, rows, used, M));

  // Table: all weeks with activities, newest first
  $('weekly-tbody').innerHTML = [...keys].reverse().map(k => {
    const w = weeks.get(k);
    return `<tr>
      <td>${k}</td>
      <td class="num">${w.acts}</td>
      <td class="num">${w.miles.toFixed(1)}</td>
      <td class="num">${fmtTime(w.secs)}</td>
      <td class="num">${fmtN(w.elev)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="5" class="empty">No activities match current filters.</td></tr>`;
}

function drawWeekly(svg, W, H, rows, used, M) {
  const m = { t: 12, r: 10, b: 26, l: 44 };
  const n = rows.length, iw = W - m.l - m.r;
  const max = d3.max(rows, r => r.w ? r.w.val : 0);
  if (!n || !(max > 0)) {
    svg.append('text').attr('x', W / 2).attr('y', H / 2).attr('text-anchor', 'middle')
      .style('font-size', '12px').text('No data in range');
    return;
  }
  const step = iw / n;
  const bw = Math.min(9, Math.max(step * 0.62, Math.min(1, step)));   // thin bars
  const t0 = rows[0].d, t1 = d3.timeMonday.offset(rows[n - 1].d, 1);
  const x = d3.scaleTime().domain([t0, t1]).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([0, max * 1.05]).range([H - m.b, m.t]);

  svg.append('g').attr('class', 'grid').attr('transform', `translate(${m.l},0)`)
    .call(d3.axisLeft(y).ticks(4).tickSize(-iw).tickFormat(axisFmt).tickPadding(6));
  svg.append('text').attr('class', 'axis-title').attr('x', m.l).attr('y', m.t - 2)
    .attr('dx', 4).attr('dy', 10).text(`${M.unit} / week`);

  // time axis: weeks → months → years depending on the span
  const maxT = Math.max(2, Math.floor(iw / 64));
  const pick = (cands, count) => cands.find(k => count / k <= maxT) || cands[cands.length - 1];
  let ticks, label, centre = 0;
  if (n <= 26) {
    const k = pick([1, 2, 4], n);
    ticks = rows.filter((_, i) => i % k === 0).map(r => r.d);
    label = d => `${MON[d.getMonth()]} ${d.getDate()}`;
    centre = step / 2;
  } else if (n <= 160) {
    const k = pick([1, 2, 3, 6], n / 4.35);
    ticks = d3.timeMonth.every(k).range(d3.timeMonth.ceil(t0), t1);
    label = (d, i) => MON[d.getMonth()] + (d.getMonth() === 0 || i === 0 ? ' ’' + String(d.getFullYear()).slice(2) : '');
  } else {
    const k = pick([1, 2, 5, 10], n / 52.2);
    ticks = d3.timeYear.every(k).range(d3.timeYear.ceil(t0), t1);
    label = d => String(d.getFullYear());
  }
  if (!centre) {
    svg.append('g').attr('class', 'grid').selectAll('line').data(ticks).join('line')
      .attr('x1', d => x(d)).attr('x2', d => x(d)).attr('y1', m.t).attr('y2', H - m.b);
  }
  svg.append('g').attr('class', 'axis').selectAll('text').data(ticks).join('text')
    .attr('x', d => x(d) + centre).attr('y', H - m.b + 16).attr('text-anchor', 'middle')
    .text((d, i) => label(d, i));

  // stacked bars
  const bars = svg.append('g');
  rows.forEach((r, i) => {
    if (!r.w) return;
    const bx = m.l + i * step + (step - bw) / 2;
    let base = 0;
    used.forEach(g => {
      const v = r.w.g[g.key];
      if (!(v > 0)) return;
      const y0 = y(base), y1 = y(base + v);
      bars.append('rect').attr('x', bx).attr('y', y1).attr('width', bw)
        .attr('height', Math.max(0, y0 - y1)).attr('fill', g.color);
      base += v;
    });
  });

  // hover: the week under the pointer
  const hl = svg.append('rect').attr('class', 'wk-hl').attr('y', m.t).attr('height', H - m.t - m.b)
    .attr('width', Math.max(step, 2)).style('display', 'none');
  svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', Math.max(0, iw)).attr('height', H - m.t - m.b)
    .attr('fill', 'transparent')
    .on('mousemove touchmove', ev => {
      const e = ev.touches ? ev.touches[0] : ev;
      const [px] = d3.pointer(e, svg.node());
      const i = Math.max(0, Math.min(n - 1, Math.floor((px - m.l) / step)));
      const r = rows[i];
      hl.style('display', null).attr('x', m.l + i * step - (Math.max(step, 2) - step) / 2);
      let body = `<b>Week of ${AR.fmtDate(r.d)}</b><br>`;
      if (!r.w) body += '<span class="dim">no activities</span>';
      else {
        if (used.length > 1) body += used.filter(g => r.w.g[g.key] > 0).map(g =>
          `${AR.swatch(g.color)}<span class="dim">${g.name}</span> ${M.fmt(r.w.g[g.key])} ${M.unit}`).join('<br>') + '<br>';
        body += `<b>${M.fmt(r.w.val)} ${M.unit}</b> <span class="dim">· ${r.w.acts} activit${r.w.acts === 1 ? 'y' : 'ies'} · ${fmtTime(r.w.secs)}</span>`;
      }
      AR.tip.show(body, e);
    })
    .on('mouseleave touchend', () => { hl.style('display', 'none'); AR.tip.hide(); });
}

// ── YEARLY ────────────────────────────────────────────────────────────────
function renderYearly() {
  const M = METRICS[metric];
  // Group by year × sport
  const data = {};
  filtered.forEach(a => {
    if (!a.date) return;
    const y = a.date.slice(0,4);
    const s = a.sport_type || 'Unknown';
    const key = `${y}|${s}`;
    if (!data[key]) data[key] = {year:y, sport:s, acts:0, miles:0, secs:0, elev:0, val:0, hrSum:0, hrN:0};
    data[key].acts++;
    data[key].miles += a.miles||0;
    data[key].secs  += a.moving_time_s||0;
    data[key].elev  += a.elev_ft||0;
    data[key].val   += M.get(a);
    if (a.average_heartrate) { data[key].hrSum += a.average_heartrate; data[key].hrN++; }
  });

  // Per-year totals for chart
  const yearTotals = {}, sportTotals = {};
  Object.values(data).forEach(d => {
    if (!yearTotals[d.year]) yearTotals[d.year] = {};
    yearTotals[d.year][d.sport] = d.val;
    sportTotals[d.sport] = (sportTotals[d.sport]||0) + d.val;
  });
  const years = Object.keys(yearTotals).sort();

  // Stacked bars: top six sports, the rest lumped into "Other"
  const topSports = Object.entries(sportTotals).filter(e => e[1] > 0)
    .sort((a,b)=>b[1]-a[1]).slice(0,6).map(e=>e[0]);
  const stack = topSports.map(s => ({
    name: s, color: sportColor(s), values: years.map(y => yearTotals[y][s] || 0),
  }));
  const other = years.map(y => Object.entries(yearTotals[y])
    .reduce((s,[sp,v]) => s + (topSports.includes(sp) ? 0 : v), 0));
  if (other.some(v => v > 0)) stack.push({ name: 'Other', color: 'var(--gray)', values: other });

  const legendEl = $('yearly-legend');
  if (stack.length > 1) AR.legend(legendEl, stack); else legendEl.innerHTML = '';
  AR.barChart('#yearly-chart', {
    labels: years, stack, height: 260, yFmt: axisFmt,
    tip: i => {
      const tot = d3.sum(stack, s => s.values[i]);
      return `<b>${years[i]}</b><br>` +
        stack.filter(s => s.values[i] > 0).map(s =>
          `${AR.swatch(s.color)}<span class="dim">${s.name}</span> ${M.fmt(s.values[i])} ${M.unit}`).join('<br>') +
        (stack.length > 1 ? `<br><b>${M.fmt(tot)} ${M.unit}</b> <span class="dim">total</span>` : '');
    },
  });

  // Table
  const rows = Object.values(data).sort((a,b) =>
    b.year.localeCompare(a.year) || b.miles - a.miles);
  $('yearly-tbody').innerHTML = rows.map(d => `<tr>
    <td>${d.year}</td>
    <td>${sportBadge(d.sport)}</td>
    <td class="num">${d.acts}</td>
    <td class="num">${d.miles.toFixed(1)}</td>
    <td class="num">${fmtTime(d.secs)}</td>
    <td class="num">${fmtN(d.elev)}</td>
    <td class="num">${d.hrN ? fmtHR(d.hrSum/d.hrN) : '—'}</td>
  </tr>`).join('') || `<tr><td colspan="7" class="empty">No activities match current filters.</td></tr>`;
}

// ── BIKES ─────────────────────────────────────────────────────────────────
function renderBikes() {
  const M = METRICS[metric];
  const fromVal = bikeFrom || ($('bike-from').value||null);
  const toVal   = bikeTo   || ($('bike-to').value||null);

  // Use global filters PLUS bike date overrides
  let src = filtered.filter(a => a.gear_id && a.gear_id.startsWith('b'));
  if (fromVal) src = src.filter(a => a.date >= fromVal);
  if (toVal)   src = src.filter(a => a.date <= toVal);

  const gear = {};
  src.forEach(a => {
    const key = a.gear_id;
    if (!gear[key]) gear[key] = {name: a.gear||key, rides:0, miles:0, secs:0, elev:0, val:0, hrSum:0, hrN:0, commutes:0};
    gear[key].rides++;
    gear[key].miles   += a.miles||0;
    gear[key].secs    += a.moving_time_s||0;
    gear[key].elev    += a.elev_ft||0;
    gear[key].val     += M.get(a);
    gear[key].commutes+= a.commute||0;
    if (a.average_heartrate) { gear[key].hrSum += a.average_heartrate; gear[key].hrN++; }
  });

  const byVal = Object.values(gear).sort((a,b) => b.val - a.val);
  const narrow = window.innerWidth < 600;
  AR.hbarChart('#bikes-chart', {
    labels: byVal.map(g => g.name), values: byVal.map(g => g.val),
    fmt: v => `${M.fmt(v)} ${M.unit}`, labelWidth: narrow ? 110 : 170, rowHeight: 28,
    tip: i => { const g = byVal[i];
      return `<b>${esc(g.name)}</b><br>${M.fmt(g.val)} ${M.unit}` +
        `<br><span class="dim">${g.rides} ride${g.rides === 1 ? '' : 's'} · ${fmtTime(g.secs)} · ${g.commutes} commute${g.commutes === 1 ? '' : 's'}</span>`; },
  });

  const rows = Object.values(gear).sort((a,b) => b.miles - a.miles);
  const tbody = $('bikes-tbody');
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">No ride data matches current filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(g => `<tr>
    <td><strong>${esc(g.name)}</strong></td>
    <td class="num">${g.rides}</td>
    <td class="num">${g.miles.toFixed(1)}</td>
    <td class="num">${fmtTime(g.secs)}</td>
    <td class="num">${fmtN(g.elev)}</td>
    <td class="num">${g.commutes}</td>
    <td class="num">${g.hrN ? fmtHR(g.hrSum/g.hrN) : '—'}</td>
  </tr>`).join('');
}

// Bike date pickers (independent of global filters)
$('bike-from').addEventListener('change', e => { bikeFrom = e.target.value||null; renderBikes(); });
$('bike-to').addEventListener('change',   e => { bikeTo   = e.target.value||null; renderBikes(); });
$('bike-reset').addEventListener('click', () => {
  bikeFrom = bikeTo = null;
  $('bike-from').value = '';
  $('bike-to').value = '';
  renderBikes();
});

// ── ACTIVITIES TABLE ──────────────────────────────────────────────────────
function renderActivities() {
  // Sort
  const mul = actSortDir;
  const sorted = [...filtered].sort((a,b) => {
    const av = a[actSortCol], bv = b[actSortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    return av < bv ? -mul : av > bv ? mul : 0;
  });

  // Pagination
  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total / ACT_PAGE_SIZE));
  actPage = Math.min(actPage, pages);
  const slice = sorted.slice((actPage-1)*ACT_PAGE_SIZE, actPage*ACT_PAGE_SIZE);

  // Update sort indicators
  document.querySelectorAll('#act-table thead th[data-col]').forEach(th => {
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.dataset.col === actSortCol)
      th.classList.add(actSortDir === 1 ? 'sorted-asc' : 'sorted-desc');
  });

  $('act-tbody').innerHTML = slice.map(a => {
    const wl = a.workout_type != null ? WORKOUT_LABELS[a.workout_type] : null;
    const badge = wl && wl !== 'Default' ? `<span class="badge flag">${wl}</span>` : '';
    const commBadge = a.commute ? `<span class="badge">commute</span>` : '';
    const link = `<a href="https://www.strava.com/activities/${a.id}" target="_blank" rel="noopener" title="Open on Strava">↗</a>`;
    const view = `<a class="act-name" href="viewer.html?id=${a.id}">${esc(a.name||'—')}</a>`;
    return `<tr>
      <td>${a.date}</td>
      <td>${link} ${view}${badge}${commBadge}</td>
      <td>${sportBadge(a.sport_type)}</td>
      <td class="num">${fmtMi(a.miles)}</td>
      <td class="num">${fmtTime(a.moving_time_s)}</td>
      <td class="num">${fmtN(a.elev_ft)}</td>
      <td class="num">${fmtHR(a.average_heartrate)}</td>
      <td class="num">${a.average_watts != null ? Math.round(a.average_watts) : '—'}</td>
      <td>${esc(a.gear||'—')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="9" class="empty">No activities match current filters.</td></tr>`;

  // Pagination controls
  const pg = $('act-pagination');
  if (pages <= 1) { pg.innerHTML=''; return; }
  const buttons = [];
  buttons.push(`<span class="info">Page ${actPage} of ${pages} (${total.toLocaleString()} activities)</span>`);
  if (actPage > 1)  buttons.push(`<button onclick="setPage(${actPage-1})">‹ Prev</button>`);
  // window of page buttons
  const lo = Math.max(1, actPage-3), hi = Math.min(pages, actPage+3);
  for (let p = lo; p <= hi; p++)
    buttons.push(`<button class="${p===actPage?'active':''}" onclick="setPage(${p})">${p}</button>`);
  if (actPage < pages) buttons.push(`<button onclick="setPage(${actPage+1})">Next ›</button>`);
  pg.innerHTML = buttons.join('');
}

window.setPage = p => { actPage = p; renderActivities(); window.scrollTo(0,0); };

// Sort by column header click
document.querySelectorAll('#act-table thead th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    if (actSortCol === th.dataset.col) actSortDir *= -1;
    else { actSortCol = th.dataset.col; actSortDir = -1; }
    actPage = 1;
    renderActivities();
  });
});

// ── NAV ───────────────────────────────────────────────────────────────────
const SECTION_TITLES = {
  weekly: 'Weekly Volume', yearly: 'Yearly Totals', bikes: 'By Bike', activities: 'Activities',
};
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    const sec = item.dataset.section;
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    $('section-' + sec).classList.add('active');
    $('section-title').textContent = SECTION_TITLES[sec] || sec;
  });
});

// ── BOOT ──────────────────────────────────────────────────────────────────
setRange(DEFAULT_RANGE_DAYS);
</script>
</body>
</html>
"""


DETAIL_SQL = """
    SELECT a.id, a.name, a.sport_type, a.start_date, a.start_date_local, a.timezone,
           a.distance_m, a.moving_time_s, a.elapsed_time_s, a.total_elevation_m,
           a.average_speed_ms, a.max_speed_ms, a.average_heartrate, a.max_heartrate,
           a.average_watts, a.device_watts, a.average_cadence, a.suffer_score,
           a.calories, a.gear_id, COALESCE(g.name, a.gear_name) AS gear_name,
           a.commute, a.trainer, a.manual, a.workout_type, a.map_summary_polyline,
           a.achievement_count, a.kudos_count, a.comment_count, a.athlete_count,
           a.photo_count, a.pr_count
    FROM activities a
    LEFT JOIN gear g ON g.id = a.gear_id
    ORDER BY a.start_date_local ASC, a.id ASC
"""


def write_stream_files(streams_db: str, out_dir: Path, rebuild: bool = False) -> set[int]:
    """Write downsampled streams/<id>.json for every activity in streams.db.

    Existing files are left alone (a stored stream never changes) unless
    `rebuild` is set, e.g. after changing the downsampling format. Returns the
    ids that have a published stream file.
    """
    con = streams_mod.open_streams_db(streams_db)
    ids = [r[0] for r in con.execute(
        "SELECT activity_id FROM streams WHERE source != 'none'")]
    out_dir.mkdir(exist_ok=True)
    written = 0
    for aid in ids:
        path = out_dir / f"{aid}.json"
        if path.exists() and not rebuild:
            continue
        ds = streams_mod.downsample(streams_mod.load(con, aid))
        path.write_text(json.dumps(ds, separators=(",", ":")), encoding="utf-8")
        written += 1
    con.close()
    keep = {f"{aid}.json" for aid in ids}
    removed = 0
    for path in out_dir.glob("*.json"):
        if path.name not in keep:
            path.unlink()
            removed += 1
    print(f"Stream files in {out_dir}/: {len(ids)} total, {written} written, {removed} removed")
    return set(ids)


def write_activity_files(db_path: str, out_dir: Path,
                         with_streams: set[int]) -> None:
    """Write one JSON per activity for viewer.html?id=<id>.

    Files are only rewritten when their contents change, and files for
    activities no longer in the DB are removed, so the daily commit only
    touches what actually changed.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(DETAIL_SQL)]
    con.close()

    out_dir.mkdir(exist_ok=True)
    keep: set[str] = set()
    written = 0
    for i, r in enumerate(rows):
        r["prev_id"] = rows[i - 1]["id"] if i > 0 else None
        r["next_id"] = rows[i + 1]["id"] if i + 1 < len(rows) else None
        r["streams"] = r["id"] in with_streams
        name = f"{r['id']}.json"
        keep.add(name)
        path = out_dir / name
        text = json.dumps(r, separators=(",", ":"), ensure_ascii=False)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            written += 1
    removed = 0
    for path in out_dir.glob("*.json"):
        if path.name not in keep:
            path.unlink()
            removed += 1
    print(f"Activity files in {out_dir}/: {len(rows)} total, {written} written, {removed} removed")


def render_html(db_path: str) -> tuple[str, int]:
    """Return (index.html text, activity count). The template is a raw string
    with plain JS braces; the two placeholders are substituted with replace()."""
    acts, bikes = load_data(db_path)

    sport_types = sorted({a["sport_type"] for a in acts if a["sport_type"]})

    data_js = (
        f"const ALL_ACTIVITIES = {json.dumps(acts, separators=(',', ':'))};\n"
        f"const BIKES = {json.dumps(bikes)};\n"
        f"const SPORT_TYPES = {json.dumps(sport_types)};\n"
    )

    html = (HTML_TEMPLATE.replace("{data_js}", data_js)
            .replace("{generated}", date.today().isoformat()))
    return html, len(acts)


def build(db_path: str, out_path: str, streams_db: str = "streams.db",
          rebuild_streams: bool = False) -> None:
    print(f"Loading data from {db_path} …")
    html, n_acts = render_html(db_path)
    Path(out_path).write_text(html, encoding="utf-8")
    size = Path(out_path).stat().st_size
    print(f"Written {out_path} ({size/1024/1024:.2f} MB, {n_acts} activities)")

    site = Path(out_path).parent
    with_streams = write_stream_files(streams_db, site / "streams", rebuild_streams)
    write_activity_files(db_path, site / "activities", with_streams)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate index.html from strava.db")
    ap.add_argument("--db",  default="strava.db",   help="SQLite DB path")
    ap.add_argument("--out", default="index.html",  help="Output HTML path")
    ap.add_argument("--streams-db", default="streams.db",
                    help="Local full-resolution streams DB (see streams.py)")
    ap.add_argument("--rebuild-streams", action="store_true",
                    help="Rewrite every streams/<id>.json, not just new ones")
    args = ap.parse_args()
    build(args.db, args.out, args.streams_db, args.rebuild_streams)


if __name__ == "__main__":
    main()
