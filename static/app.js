/* App shell: data layer, feed, filters, detail panel, ingest status. */
import { Globe, sevColor, catColor } from '/static/globe.js';

const CATEGORIES = ['conflict', 'unrest', 'military', 'diplomacy', 'disaster', 'hazard', 'other'];
const CAT_LABELS = {
  conflict: 'Conflict', unrest: 'Unrest', military: 'Military',
  diplomacy: 'Diplomacy', disaster: 'Disaster', hazard: 'Hazard', other: 'Other',
};
const CHANNEL_LABELS = { gdelt: 'GDELT', usgs: 'USGS', gdacs: 'GDACS', rss: 'RSS', sample: 'Sample' };
const ZONE_SEV_LABELS = { war: 'Active War', high: 'High Tension', elevated: 'Elevated' };
const REFRESH_SEC = 60;

const LAYERS = [
  { key: 'events', label: 'Events', color: '#c44038' },
  { key: 'zones', label: 'Conflict Zones', color: '#d4882a' },
  { key: 'heatmap', label: 'Density Heatmap', color: '#a058c8' },
  { key: 'labels', label: 'Country Labels', color: '#c9a227' },
  { key: 'dayNight', label: 'Day / Night Line', color: '#7a9472' },
  { key: 'liveSun', label: 'Live Sun Position', color: '#9a948c' },
  { key: 'autoRotate', label: 'Auto Rotate', color: '#7a756e' },
];

const SHORTCUTS = [
  ['/', 'Focus search'],
  ['r', 'Refresh all feeds'],
  ['j / k', 'Next / previous event'],
  ['l', 'Toggle labels'],
  ['c', 'Toggle conflict zones'],
  ['h', 'Toggle heatmap'],
  ['d', 'Toggle day/night line'],
  ['a', 'Toggle auto-rotate'],
  ['?', 'Show shortcuts'],
  ['Esc', 'Close panels'],
];

const state = {
  events: [],
  conflictZones: [],
  cats: new Set(CATEGORIES),
  minSev: 0,
  sinceHours: 72,
  q: '',
  selectedId: null,
  selectedZoneId: null,
  mode: 'connecting',
  feedIdx: -1,
  layers: {
    events: true, zones: true, heatmap: false, labels: true,
    dayNight: true, liveSun: true, autoRotate: true,
  },
};

const $ = (id) => document.getElementById(id);
const tooltip = $('tooltip');

function placeTooltip(x, y) {
  const r = tooltip.getBoundingClientRect();
  tooltip.style.left = Math.min(x + 16, innerWidth - r.width - 12) + 'px';
  tooltip.style.top = Math.min(y + 16, innerHeight - r.height - 12) + 'px';
}

const globe = new Globe($('scene'), {
  onHover(ev, x, y) {
    if (!ev) {
      if (!state._zoneHover) tooltip.classList.remove('visible', 'zone-tip');
      return;
    }
    tooltip.classList.remove('zone-tip');
    tooltip.querySelector('.tt-badges').innerHTML =
      `<span class="badge cat-${ev.category}">${esc(CAT_LABELS[ev.category] || ev.category)}</span>` +
      `<span class="badge channel">${esc(CHANNEL_LABELS[ev.channel] || ev.channel)}</span>`;
    tooltip.querySelector('.tt-title').textContent = ev.title;
    tooltip.querySelector('.tt-meta').textContent =
      `${timeAgo(ev.ts)} · ${sevLabel(ev.severity)} · ${ev.place || ev.country || 'Unknown'}`;
    tooltip.classList.add('visible');
    placeTooltip(x, y);
  },
  onZoneHover(zone, x, y) {
    state._zoneHover = zone;
    if (!zone) {
      if (!state._eventHover) tooltip.classList.remove('visible', 'zone-tip');
      return;
    }
    tooltip.classList.add('zone-tip', 'visible');
    tooltip.querySelector('.tt-badges').innerHTML =
      `<span class="badge channel">${esc(ZONE_SEV_LABELS[zone.severity] || zone.severity)}</span>`;
    tooltip.querySelector('.tt-title').textContent = zone.label;
    tooltip.querySelector('.tt-meta').textContent = zone.description || '';
    placeTooltip(x, y);
  },
  onSelect(ev) { selectEvent(ev, { fly: false }); },
  onZoneSelect(zone) { selectZone(zone, { fly: false }); },
});
window.__globe = globe; // console/debug handle

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function timeAgo(ts) {
  const m = Math.max(0, (Date.now() - Date.parse(ts)) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${Math.round(m)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}

function sevClass(s) { return s >= 0.7 ? 'sev-high' : s >= 0.45 ? 'sev-mid' : 'sev-low'; }
function sevLabel(s) {
  if (s >= 0.7) return 'High';
  if (s >= 0.45) return 'Medium';
  return 'Low';
}

function cleanSummary(text) {
  return String(text || '')
    .replace(/\s+/g, ' ')
    .replace(/Please refer to the attached file\.?\s*/gi, '')
    .trim()
    .slice(0, 600);
}

function setLoaderStep(msg) {
  const el = $('loader-step');
  if (el) el.textContent = msg;
}

// ---------------------------------------------------------------- data

function eventQueryParams() {
  const p = new URLSearchParams({
    since_hours: state.sinceHours,
    limit: 1500,
    min_severity: state.minSev,
  });
  if (state.q) p.set('q', state.q);
  return p;
}

async function fetchEvents() {
  try {
    const r = await fetch(`/api/events?${eventQueryParams()}`);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    state.mode = 'live';
    state.events = data.events;
    if (state.events.length === 0 && !state.q && !state._sampleNoted) {
      await loadSamples();
    }
  } catch {
    await loadSamples();
  }
  render();
}

async function fetchStats() {
  try {
    const r = await fetch('/api/stats');
    if (!r.ok) return;
    const data = await r.json();
    renderIngest(data.ingest || []);
  } catch { /* ignore */ }
}

async function loadSamples() {
  if (state._samples) { state.events = state._samples; state.mode = 'sample'; return; }
  try {
    const r = await fetch('/data/sample-events.json');
    const data = await r.json();
    const now = Date.now();
    state._samples = data.events.map((e) => ({
      ...e,
      ts: new Date(now - e.age_minutes * 60000).toISOString().replace(/\.\d+Z$/, 'Z'),
    }));
    state.events = state._samples;
    state.mode = 'sample';
  } catch { state.events = []; }
}

function buildHeatmap(evs) {
  const step = 6;
  const cells = new Map();
  for (const ev of evs) {
    const lat = Math.round(ev.lat / step) * step;
    const lon = Math.round(ev.lon / step) * step;
    const key = `${lat},${lon}`;
    const cur = cells.get(key) || { lat, lon, count: 0, sev: 0 };
    cur.count += 1;
    cur.sev += ev.severity;
    cells.set(key, cur);
  }
  const dense = [...cells.values()].filter((c) => c.count >= 3);
  if (!dense.length) return [];
  const max = Math.max(...dense.map((c) => c.count));
  return dense.map((c) => ({
    lat: c.lat, lon: c.lon, count: c.count,
    intensity: (c.count / max) * 0.7 + (c.sev / c.count) * 0.3,
  }));
}

function applyLayers() {
  globe.setLayers({
    events: state.layers.events,
    zones: state.layers.zones,
    heatmap: state.layers.heatmap,
    labels: state.layers.labels,
    dayNight: state.layers.dayNight,
    liveSun: state.layers.liveSun,
    autoRotate: state.layers.autoRotate,
  });
}

function toggleLayer(key) {
  state.layers[key] = !state.layers[key];
  applyLayers();
  renderLayerPanel();
}

function layerCounts() {
  const evs = visibleEvents();
  return {
    events: evs.length,
    zones: state.conflictZones.length,
    heatmap: buildHeatmap(evs).length,
    labels: '—',
    dayNight: '—',
    liveSun: '—',
    autoRotate: '—',
  };
}

function renderLayerPanel() {
  const el = $('layer-list');
  if (!el) return;
  const counts = layerCounts();
  el.innerHTML = '';
  for (const layer of LAYERS) {
    const btn = document.createElement('button');
    btn.className = 'layer-btn' + (state.layers[layer.key] ? ' on' : '');
    btn.innerHTML =
      `<span class="layer-dot" style="color:${layer.color}"></span>` +
      `<span class="layer-name">${layer.label}</span>` +
      `<span class="layer-count">${counts[layer.key]}</span>`;
    btn.onclick = () => toggleLayer(layer.key);
    el.appendChild(btn);
  }
}

function renderTicker(evs) {
  const el = $('ticker-content');
  if (!el) return;
  const items = [...evs]
    .sort((a, b) => b.severity - a.severity || Date.parse(b.ts) - Date.parse(a.ts))
    .slice(0, 20);
  if (!items.length) {
    el.innerHTML = '<span class="ticker-item"><span class="t-title">Awaiting intelligence…</span></span>';
    return;
  }
  const html = items.map((ev) =>
    `<span class="ticker-item">` +
      `<span class="t-sev" style="background:${catColor(ev.category)}"></span>` +
      `<span class="t-cat">${esc(CAT_LABELS[ev.category])}</span>` +
      `<span class="t-title">${esc(ev.title)}</span>` +
      `<span class="t-cat">${timeAgo(ev.ts)}</span>` +
    `</span>`
  ).join('');
  el.innerHTML = html + html;
}

function renderShortcuts() {
  const el = $('shortcuts-list');
  if (!el) return;
  el.innerHTML = SHORTCUTS.map(([k, d]) =>
    `<dt><kbd>${esc(k)}</kbd></dt><dd>${esc(d)}</dd>`
  ).join('');
}

function openShortcuts() { $('shortcuts-modal').hidden = false; }
function closeShortcuts() { $('shortcuts-modal').hidden = true; }

function visibleEvents() {
  const q = state.q.toLowerCase();
  return state.events.filter((e) => {
    if (!state.cats.has(e.category)) return false;
    if (state.mode === 'sample') {
      if (e.severity < state.minSev) return false;
      if (q && !(e.title + ' ' + e.place + ' ' + e.country + ' ' + e.actors).toLowerCase().includes(q)) {
        return false;
      }
    }
    return true;
  });
}

// ---------------------------------------------------------------- render

function render() {
  const evs = visibleEvents();
  globe.setEvents(evs);
  globe.setHeatmap(buildHeatmap(evs));
  renderFeed(evs);
  renderChips();
  renderLayerPanel();
  renderTicker(evs);
  $('stat-count').textContent = evs.length.toLocaleString();
  $('feed-count').textContent = evs.length.toLocaleString();
  $('stat-window').textContent = state.sinceHours >= 24 ? `${state.sinceHours / 24}d` : `${state.sinceHours}h`;
  const conn = $('conn');
  conn.className = state.mode;
  conn.querySelector('.conn-label').textContent =
    state.mode === 'live' ? 'Live' : state.mode === 'sample' ? 'Sample Data' : 'Connecting…';
}

function renderFeed(evs) {
  const feed = $('feed');
  feed.innerHTML = '';
  if (!evs.length) {
    feed.innerHTML = state.q
      ? '<div class="empty"><strong>No results</strong>Try a different search term or widen your filters.</div>'
      : '<div class="empty"><strong>No events</strong>Adjust category filters or time window to see more.</div>';
    return;
  }
  const frag = document.createDocumentFragment();
  const pinIcon = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1C4.3 1 3 2.3 3 4c0 2.5 3 6 3 6s3-3.5 3-6c0-1.7-1.3-3-3-3z" fill="currentColor"/></svg>';
  for (const ev of evs.slice(0, 400)) {
    const el = document.createElement('div');
    el.className = `feed-item ${sevClass(ev.severity)}` + (ev.id === state.selectedId ? ' selected' : '');
    el.dataset.id = ev.id;
    el.innerHTML =
      `<div class="row-top">` +
        `<span class="sev-dot" style="background:${catColor(ev.category)}"></span>` +
        `<span class="cat-badge cat-${ev.category}">${esc(CAT_LABELS[ev.category])}</span>` +
        `<span class="meta-src">${esc(ev.source)}</span>` +
        `<span class="meta-time">${timeAgo(ev.ts)}</span>` +
      `</div>` +
      `<div class="title">${esc(ev.title)}</div>` +
      (ev.place ? `<div class="place">${pinIcon}${esc(ev.place)}</div>` : '');
    el.onclick = () => selectEvent(ev, { fly: true });
    frag.appendChild(el);
  }
  feed.appendChild(frag);
}

function renderChips() {
  const counts = {};
  for (const e of state.events) counts[e.category] = (counts[e.category] || 0) + 1;
  const row = $('cat-chips');
  row.innerHTML = '';
  for (const cat of CATEGORIES) {
    const chip = document.createElement('button');
    chip.className = 'chip' + (state.cats.has(cat) ? ' on' : '');
    chip.dataset.cat = cat;
    chip.innerHTML = `${CAT_LABELS[cat]}<span class="n">${counts[cat] || 0}</span>`;
    chip.onclick = () => {
      if (state.cats.has(cat) && state.cats.size === 1) state.cats = new Set(CATEGORIES);
      else if (state.cats.has(cat)) state.cats.delete(cat);
      else state.cats.add(cat);
      render();
    };
    row.appendChild(chip);
  }
}

function renderIngest(channels) {
  const el = $('ingest-channels');
  if (!el) return;
  el.innerHTML = '';
  const order = ['gdelt', 'usgs', 'gdacs', 'rss'];
  for (const ch of order) {
    const row = channels.find((c) => c.channel === ch);
    const chip = document.createElement('span');
    chip.className = 'ingest-chip' + (row?.last_error ? ' err' : row ? ' ok' : '');
    const ago = row?.last_run ? timeAgo(row.last_run) : '—';
    chip.textContent = `${(CHANNEL_LABELS[ch] || ch).toUpperCase()} · ${ago}`;
    chip.title = row?.last_error || (row ? `${row.last_count} ingested` : 'Pending');
    el.appendChild(chip);
  }
}

function selectEvent(ev, { fly }) {
  state.selectedId = ev.id;
  state.selectedZoneId = null;
  state.feedIdx = visibleEvents().findIndex((e) => e.id === ev.id);
  globe.setSelected(ev.id);
  if (fly) globe.flyTo(ev.lat, ev.lon);

  $('detail-badges').innerHTML =
    `<span class="badge cat-${ev.category}">${esc(CAT_LABELS[ev.category])}</span>` +
    `<span class="badge channel">${esc(CHANNEL_LABELS[ev.channel] || ev.channel)}</span>` +
    `<span class="badge channel">${esc(ev.source)}</span>`;

  $('detail-title').textContent = ev.title;
  $('detail-summary').textContent = cleanSummary(ev.summary) || 'No summary available.';
  $('detail-sev-text').textContent = `${sevLabel(ev.severity)} (${ev.severity.toFixed(2)})`;
  $('detail-sev').innerHTML =
    `<i style="width:${(ev.severity * 100).toFixed(0)}%;background:${sevColor(ev.severity)}"></i>`;
  document.querySelector('.sevbar-wrap').style.display = '';

  const kv = $('detail-kv');
  kv.innerHTML = '';
  const rows = [
    ['Time', new Date(ev.ts).toUTCString().replace('GMT', 'UTC')],
    ['Location', ev.place || `${ev.lat.toFixed(2)}°, ${ev.lon.toFixed(2)}°`],
    ['Country', ev.country],
    ['Actors', ev.actors],
    ['Channel', CHANNEL_LABELS[ev.channel] || ev.channel],
  ];
  for (const [k, v] of rows) {
    if (!v) continue;
    kv.insertAdjacentHTML('beforeend', `<dt>${k}</dt><dd>${esc(v)}</dd>`);
  }

  const link = $('detail-link');
  link.innerHTML = 'Read source article <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 12L12 4M7 4h5v5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  if (ev.url) { link.href = ev.url; link.style.display = 'inline-flex'; }
  else link.style.display = 'none';

  $('detail').classList.add('open');
  document.querySelectorAll('.feed-item').forEach((el) => el.classList.remove('selected'));
  const item = document.querySelector(`.feed-item[data-id="${ev.id}"]`);
  if (item) { item.classList.add('selected'); item.scrollIntoView({ block: 'nearest' }); }
}

function selectZone(zone, { fly }) {
  state.selectedZoneId = zone.id;
  state.selectedId = null;
  state.feedIdx = -1;
  globe.setSelected(null);
  if (fly) globe.flyTo(zone.lat, zone.lon);

  $('detail-badges').innerHTML =
    `<span class="badge channel">Conflict Zone</span>` +
    `<span class="badge channel">${esc(ZONE_SEV_LABELS[zone.severity] || zone.severity)}</span>`;

  $('detail-title').textContent = zone.label;
  $('detail-summary').textContent = zone.description || 'Monitored tension zone.';
  document.querySelector('.sevbar-wrap').style.display = 'none';

  const kv = $('detail-kv');
  kv.innerHTML = '';
  const rows = [
    ['Coordinates', `${zone.lat.toFixed(2)}°, ${zone.lon.toFixed(2)}°`],
    ['Severity', ZONE_SEV_LABELS[zone.severity] || zone.severity],
    ['Type', 'Static OSINT overlay'],
  ];
  for (const [k, v] of rows) {
    kv.insertAdjacentHTML('beforeend', `<dt>${k}</dt><dd>${esc(v)}</dd>`);
  }

  const link = $('detail-link');
  if (zone.url) {
    link.href = zone.url;
    link.innerHTML = 'Open live map <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 12L12 4M7 4h5v5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    link.style.display = 'inline-flex';
  } else link.style.display = 'none';

  $('detail').classList.add('open');
  document.querySelectorAll('.feed-item').forEach((el) => el.classList.remove('selected'));
}

function closeDetail() {
  $('detail').classList.remove('open');
  state.selectedId = null;
  state.selectedZoneId = null;
  state.feedIdx = -1;
  globe.setSelected(null);
  document.querySelectorAll('.feed-item').forEach((el) => el.classList.remove('selected'));
}

// ---------------------------------------------------------------- controls

$('detail-close').onclick = closeDetail;

$('search').oninput = (e) => {
  const v = e.target.value;
  $('search-clear').hidden = !v;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = v.trim();
    if (state.mode === 'live') fetchEvents();
    else render();
  }, 280);
};

$('search-clear').onclick = () => {
  $('search').value = '';
  $('search-clear').hidden = true;
  state.q = '';
  if (state.mode === 'live') fetchEvents();
  else render();
  $('search').focus();
};

$('sel-window').onchange = (e) => { state.sinceHours = +e.target.value; fetchEvents(); };
$('sel-sev').onchange = (e) => {
  state.minSev = +e.target.value;
  if (state.mode === 'live') fetchEvents();
  else render();
};

$('shortcuts-close').onclick = closeShortcuts;
$('shortcuts-modal').querySelector('.shortcuts-backdrop').onclick = closeShortcuts;
renderShortcuts();

let searchTimer;
let refreshCountdown = REFRESH_SEC;
let refreshInFlight = false;

async function forceRefresh() {
  const btn = $('refresh-now');
  if (refreshInFlight) return;
  refreshInFlight = true;
  btn.disabled = true;
  const prevLabel = btn.textContent;
  btn.textContent = 'Updating…';
  try {
    const r = await fetch('/api/refresh', { method: 'POST' });
    const data = await r.json();
    if (!data.ok) {
      btn.textContent = data.status === 'busy' ? 'Busy…' : 'Failed';
      setTimeout(() => { btn.textContent = prevLabel; }, 2000);
      return;
    }
    const t0 = Date.now();
    while (Date.now() - t0 < 45000) {
      await new Promise((res) => setTimeout(res, 2000));
      await fetchStats();
      const anyRecent = [...$('ingest-channels').querySelectorAll('.ingest-chip.ok')].length > 0;
      if (anyRecent && Date.now() - t0 > 4000) break;
    }
    await fetchEvents();
    refreshCountdown = REFRESH_SEC;
  } catch {
    btn.textContent = 'Failed';
    setTimeout(() => { btn.textContent = prevLabel; }, 2000);
  } finally {
    btn.disabled = false;
    if (btn.textContent === 'Updating…') btn.textContent = prevLabel;
    refreshInFlight = false;
  }
}

function tickClock() {
  $('clock').textContent = new Date().toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
}

function tickRefresh() {
  refreshCountdown--;
  if (refreshCountdown <= 0) {
    refreshCountdown = REFRESH_SEC;
    fetchEvents();
    fetchStats();
  }
  $('refresh-timer').textContent = `auto ${refreshCountdown}s`;
}

$('refresh-now').onclick = forceRefresh;

function inInput() {
  const tag = document.activeElement?.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeShortcuts(); closeDetail(); return; }
  if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
    if (!inInput()) { e.preventDefault(); openShortcuts(); }
    return;
  }
  if (inInput()) return;

  if (e.key === '/') { e.preventDefault(); $('search').focus(); return; }
  if (e.key === 'r' && !e.ctrlKey && !e.metaKey) { forceRefresh(); return; }
  if (e.key === 'l') { toggleLayer('labels'); return; }
  if (e.key === 'c') { toggleLayer('zones'); return; }
  if (e.key === 'h') { toggleLayer('heatmap'); return; }
  if (e.key === 'd') { toggleLayer('dayNight'); return; }
  if (e.key === 'a') { toggleLayer('autoRotate'); return; }

  const evs = visibleEvents();
  if (!evs.length) return;
  if (e.key === 'j' || e.key === 'ArrowDown') {
    e.preventDefault();
    const next = Math.min(state.feedIdx + 1, evs.length - 1);
    selectEvent(evs[next], { fly: true });
  }
  if (e.key === 'k' || e.key === 'ArrowUp') {
    e.preventDefault();
    const prev = Math.max(state.feedIdx - 1, 0);
    selectEvent(evs[prev], { fly: true });
  }
});

// ---------------------------------------------------------------- boot

(async function boot() {
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(tickRefresh, 1000);

  setLoaderStep('Loading cartography…');
  await globe.init();

  setLoaderStep('Loading conflict zones…');
  try {
    const zr = await fetch('/data/conflict-zones.json');
    const zd = await zr.json();
    state.conflictZones = zd.zones || [];
    globe.setConflictZones(state.conflictZones);
  } catch { /* optional layer */ }

  applyLayers();
  renderLayerPanel();

  setLoaderStep('Fetching live events…');
  await Promise.all([fetchEvents(), fetchStats()]);

  $('loading').classList.add('done');
})();