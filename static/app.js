/* App shell: data fetching, feed, filters, detail panel, clock. */
import { Globe, sevColor } from '/static/globe.js';

const CATEGORIES = ['conflict', 'unrest', 'military', 'diplomacy', 'disaster', 'hazard', 'other'];

const state = {
  events: [],
  cats: new Set(CATEGORIES),
  minSev: 0,
  sinceHours: 72,
  q: '',
  selectedId: null,
  mode: 'connecting', // live | sample
};

const $ = (id) => document.getElementById(id);
const tooltip = $('tooltip');

const globe = new Globe($('scene'), {
  onHover(ev, x, y) {
    if (!ev) { tooltip.style.display = 'none'; return; }
    tooltip.innerHTML =
      `<div class="tmeta">${esc(ev.category)} · ${timeAgo(ev.ts)} · sev ${ev.severity.toFixed(2)}</div>` +
      `<div>${esc(ev.title)}</div>`;
    tooltip.style.display = 'block';
    const r = tooltip.getBoundingClientRect();
    tooltip.style.left = Math.min(x + 14, innerWidth - r.width - 10) + 'px';
    tooltip.style.top = Math.min(y + 14, innerHeight - r.height - 10) + 'px';
  },
  onSelect(ev) { select(ev, { fly: false }); },
});

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function timeAgo(ts) {
  const m = Math.max(0, (Date.now() - Date.parse(ts)) / 60000);
  if (m < 60) return `${Math.round(m)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}

function sevClass(s) { return s >= 0.7 ? 'sev-high' : s >= 0.45 ? 'sev-mid' : 'sev-low'; }

// ---------------------------------------------------------------- data

async function fetchEvents() {
  try {
    const r = await fetch(`/api/events?since_hours=${state.sinceHours}&limit=1500`);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    state.mode = 'live';
    state.events = data.events;
    if (state.events.length === 0 && !state._sampleNoted) {
      // backend up but DB still empty (first ingest in flight) — show samples meanwhile
      await loadSamples();
    }
  } catch {
    await loadSamples();
  }
  render();
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
  return state.events.filter((e) =>
    state.cats.has(e.category) &&
    e.severity >= state.minSev &&
    (!q || (e.title + ' ' + e.place + ' ' + e.country + ' ' + e.actors).toLowerCase().includes(q))
  );
}

// ---------------------------------------------------------------- render

function render() {
  const evs = visibleEvents();
  globe.setEvents(evs);
  renderFeed(evs);
  renderChips();
  $('stat-count').textContent = evs.length;
  $('stat-window').textContent = state.sinceHours >= 24 ? `${state.sinceHours / 24}d` : `${state.sinceHours}h`;
  const conn = $('conn');
  conn.className = state.mode;
  conn.querySelector('span:last-child').textContent =
    state.mode === 'live' ? 'LIVE' : state.mode === 'sample' ? 'SAMPLE DATA' : '…';
}

function renderFeed(evs) {
  const feed = $('feed');
  feed.innerHTML = '';
  if (!evs.length) {
    feed.innerHTML = '<div class="empty">No events match the current filters.</div>';
    return;
  }
  const frag = document.createDocumentFragment();
  for (const ev of evs.slice(0, 400)) {
    const el = document.createElement('div');
    el.className = `feed-item ${sevClass(ev.severity)}` + (ev.id === state.selectedId ? ' selected' : '');
    el.innerHTML =
      `<div class="meta"><span class="cat">${esc(ev.category)}</span><span>${timeAgo(ev.ts)}</span><span>${esc(ev.source)}</span></div>` +
      `<div class="title">${esc(ev.title)}</div>` +
      (ev.place ? `<div class="place">${esc(ev.place)}</div>` : '');
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
    chip.innerHTML = `${cat}<span class="n">${counts[cat] || 0}</span>`;
    chip.onclick = () => {
      // plain click = toggle; if it would empty the set, solo it instead
      if (state.cats.has(cat) && state.cats.size === 1) state.cats = new Set(CATEGORIES);
      else if (state.cats.has(cat)) state.cats.delete(cat);
      else state.cats.add(cat);
      render();
    };
    row.appendChild(chip);
  }
}

function select(ev, { fly }) {
  state.selectedId = ev.id;
  globe.setSelected(ev.id);
  if (fly) globe.flyTo(ev.lat, ev.lon);
  $('detail-title').textContent = ev.title;
  $('detail-summary').textContent = ev.summary || 'No summary available.';
  const kv = $('detail-kv');
  kv.innerHTML = '';
  const rows = [
    ['Time', new Date(ev.ts).toUTCString().replace('GMT', 'UTC')],
    ['Category', ev.category],
    ['Severity', `${ev.severity.toFixed(2)}`],
    ['Location', ev.place || `${ev.lat.toFixed(2)}, ${ev.lon.toFixed(2)}`],
    ['Country', ev.country],
    ['Actors', ev.actors],
    ['Source', ev.source],
    ['Channel', ev.channel],
  ];
  for (const [k, v] of rows) {
    if (!v) continue;
    kv.insertAdjacentHTML('beforeend', `<dt>${k}</dt><dd>${esc(v)}</dd>`);
  }
  $('detail-sev').innerHTML =
    `<i style="width:${(ev.severity * 100).toFixed(0)}%;background:${sevColor(ev.severity)}"></i>`;
  const link = $('detail-link');
  if (ev.url) { link.href = ev.url; link.style.display = 'inline-block'; }
  else link.style.display = 'none';
  $('detail').classList.add('open');
  document.querySelectorAll('.feed-item').forEach((el) => el.classList.remove('selected'));
  const idx = visibleEvents().findIndex((e) => e.id === ev.id);
  const item = $('feed').children[idx];
  if (item && item.classList) { item.classList.add('selected'); item.scrollIntoView({ block: 'nearest' }); }
}

// ---------------------------------------------------------------- controls

$('detail-close').onclick = () => {
  $('detail').classList.remove('open');
  state.selectedId = null;
  globe.setSelected(null);
  document.querySelectorAll('.feed-item').forEach((el) => el.classList.remove('selected'));
};

let searchTimer;
$('search').oninput = (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 180);
};

$('sel-window').onchange = (e) => {
  state.sinceHours = +e.target.value;
  fetchEvents();
};
$('sel-sev').onchange = (e) => { state.minSev = +e.target.value; render(); };

function tickClock() {
  $('clock').textContent = new Date().toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
}

// ---------------------------------------------------------------- boot

(async function boot() {
  tickClock();
  setInterval(tickClock, 1000);
  await globe.init();
  await fetchEvents();
  $('loading').classList.add('done');
  setInterval(fetchEvents, 60000);
})();
