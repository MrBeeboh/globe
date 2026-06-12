/* App shell: data layer, feed, filters, detail panel, ingest status. */
import { Globe, sevColor } from '/static/globe.js';

const CATEGORIES = ['conflict', 'unrest', 'military', 'diplomacy', 'disaster', 'hazard', 'other'];
const CAT_LABELS = {
  conflict: 'Conflict', unrest: 'Unrest', military: 'Military',
  diplomacy: 'Diplomacy', disaster: 'Disaster', hazard: 'Hazard', other: 'Other',
};
const CHANNEL_LABELS = { gdelt: 'GDELT', usgs: 'USGS', gdacs: 'GDACS', rss: 'RSS', sample: 'Sample' };
const REFRESH_SEC = 60;

const state = {
  events: [],
  cats: new Set(CATEGORIES),
  minSev: 0,
  sinceHours: 72,
  q: '',
  selectedId: null,
  mode: 'connecting',
  feedIdx: -1,
};

const $ = (id) => document.getElementById(id);
const tooltip = $('tooltip');

const globe = new Globe($('scene'), {
  onHover(ev, x, y) {
    if (!ev) { tooltip.classList.remove('visible'); return; }
    tooltip.querySelector('.tt-badges').innerHTML =
      `<span class="badge cat-${ev.category}">${esc(CAT_LABELS[ev.category] || ev.category)}</span>` +
      `<span class="badge channel">${esc(CHANNEL_LABELS[ev.channel] || ev.channel)}</span>`;
    tooltip.querySelector('.tt-title').textContent = ev.title;
    tooltip.querySelector('.tt-meta').textContent =
      `${timeAgo(ev.ts)} · ${sevLabel(ev.severity)} · ${ev.place || ev.country || 'Unknown'}`;
    tooltip.classList.add('visible');
    const r = tooltip.getBoundingClientRect();
    tooltip.style.left = Math.min(x + 16, innerWidth - r.width - 12) + 'px';
    tooltip.style.top = Math.min(y + 16, innerHeight - r.height - 12) + 'px';
  },
  onSelect(ev) { select(ev, { fly: false }); },
});

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
  renderFeed(evs);
  renderChips();
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
        `<span class="sev-dot" style="background:${sevColor(ev.severity)}"></span>` +
        `<span class="cat-badge cat-${ev.category}">${esc(CAT_LABELS[ev.category])}</span>` +
        `<span class="meta-src">${esc(ev.source)}</span>` +
        `<span class="meta-time">${timeAgo(ev.ts)}</span>` +
      `</div>` +
      `<div class="title">${esc(ev.title)}</div>` +
      (ev.place ? `<div class="place">${pinIcon}${esc(ev.place)}</div>` : '');
    el.onclick = () => select(ev, { fly: true });
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

function select(ev, { fly }) {
  state.selectedId = ev.id;
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
  if (ev.url) { link.href = ev.url; link.style.display = 'inline-flex'; }
  else link.style.display = 'none';

  $('detail').classList.add('open');
  document.querySelectorAll('.feed-item').forEach((el) => el.classList.remove('selected'));
  const item = document.querySelector(`.feed-item[data-id="${ev.id}"]`);
  if (item) { item.classList.add('selected'); item.scrollIntoView({ block: 'nearest' }); }
}

function closeDetail() {
  $('detail').classList.remove('open');
  state.selectedId = null;
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

$('labels-toggle').onclick = (e) => {
  const btn = e.currentTarget;
  const on = btn.classList.toggle('active');
  globe.setLabelsVisible(on);
};

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

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeDetail(); return; }
  if (e.key === '/' && document.activeElement !== $('search')) {
    e.preventDefault(); $('search').focus(); return;
  }
  if (e.key === 'r' && document.activeElement !== $('search') && !e.ctrlKey && !e.metaKey) {
    forceRefresh(); return;
  }
  const evs = visibleEvents();
  if (!evs.length) return;
  if (e.key === 'j' || e.key === 'ArrowDown') {
    e.preventDefault();
    const next = Math.min(state.feedIdx + 1, evs.length - 1);
    select(evs[next], { fly: true });
  }
  if (e.key === 'k' || e.key === 'ArrowUp') {
    e.preventDefault();
    const prev = Math.max(state.feedIdx - 1, 0);
    select(evs[prev], { fly: true });
  }
});

// ---------------------------------------------------------------- boot

(async function boot() {
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(tickRefresh, 1000);

  setLoaderStep('Loading cartography…');
  await globe.init();

  setLoaderStep('Fetching live events…');
  await Promise.all([fetchEvents(), fetchStats()]);

  $('loading').classList.add('done');
})();