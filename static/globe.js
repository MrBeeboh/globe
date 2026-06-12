/* Professional globe renderer: procedural basemap, atmosphere, labels, event markers. */
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const PALETTE = {
  oceanDeep: '#061a30',
  oceanMid: '#0c3d66',
  oceanTropic: '#1565a0',
  oceanShallow: '#2a9cc4',
  coast: 'rgba(180, 230, 245, 0.75)',
  graticule: 'rgba(255, 255, 255, 0.04)',
  border3d: 0xc8e0ec,
  biomes: [
    [90, '#e8eef2'], [74, '#d0dde0'], [66, '#7a9a7c'], [58, '#3d6b3a'],
    [46, '#4a7a42'], [36, '#8a9a52'], [27, '#b8a070'], [20, '#c4a060'],
    [12, '#6a9a50'], [4, '#3d7a3a'], [0, '#357a38'],
  ],
};

// Event country strings → Natural Earth topojson names
const EVENT_COUNTRY_ALIASES = {
  'United States': 'United States of America',
  'United States of America': 'United States of America',
  'USA': 'United States of America',
  'UK': 'United Kingdom',
  'Britain': 'United Kingdom',
  'Russia': 'Russia',
  'Russian Federation': 'Russia',
  'The Democratic Republic of Congo': 'Dem. Rep. Congo',
  'Democratic Republic of Congo': 'Dem. Rep. Congo',
  'DR Congo': 'Dem. Rep. Congo',
  'DRC': 'Dem. Rep. Congo',
  'Dem. Rep. Congo': 'Dem. Rep. Congo',
  'Central African Republic': 'Central African Rep.',
  'Central African Rep.': 'Central African Rep.',
  'South Sudan': 'S. Sudan',
  'S. Sudan': 'S. Sudan',
  'Ivory Coast': "Côte d'Ivoire",
  'Czech Republic': 'Czechia',
  'Burma': 'Myanmar',
  'Macedonia': 'Macedonia',
  'North Macedonia': 'Macedonia',
  'UAE': 'United Arab Emirates',
  'Emirates': 'United Arab Emirates',
  'Bosnia': 'Bosnia and Herz.',
  'Dominican Republic': 'Dominican Rep.',
  'Equatorial Guinea': 'Eq. Guinea',
  'Solomon Islands': 'Solomon Is.',
  'Palestinian': 'Palestine',
  'Gaza Strip': 'Palestine',
};

const SHORT_NAMES = {
  'United States of America': 'USA',
  'United Kingdom': 'UK',
  'Dem. Rep. Congo': 'DR Congo',
  'Central African Rep.': 'CAR',
  'Dominican Rep.': 'Dom. Rep.',
  'Bosnia and Herz.': 'Bosnia',
  'Antigua and Barb.': 'Antigua',
  'Eq. Guinea': 'Eq. Guinea',
  'S. Sudan': 'S. Sudan',
  'St. Vin. and Gren.': 'St. Vincent',
  'St. Kitts and Nevis': 'St. Kitts',
  'St. Pierre and Miquelon': 'St. Pierre',
  'St-Barthélemy': 'St. Barts',
  'St-Martin': 'St. Martin',
  'São Tomé and Principe': 'São Tomé',
  'Fr. S. Antarctic Lands': 'Fr. Antarctic',
  'Fr. Polynesia': 'Fr. Polynesia',
  'Heard I. and McDonald Is.': 'Heard Is.',
  'Br. Indian Ocean Ter.': 'BIOT',
  'N. Mariana Is.': 'N. Mariana',
  'U.S. Virgin Is.': 'USVI',
  'British Virgin Is.': 'UKVI',
  'Turks and Caicos Is.': 'Turks & Caicos',
  'Wallis and Futuna Is.': 'Wallis',
  'Marshall Is.': 'Marshall',
  'Solomon Is.': 'Solomon',
  'Cook Is.': 'Cook',
  'Cayman Is.': 'Cayman',
  'Faeroe Is.': 'Faroe',
  'Falkland Is.': 'Falkland',
  'Pitcairn Is.': 'Pitcairn',
  'S. Geo. and the Is.': 'S. Georgia',
  'United Arab Emirates': 'UAE',
  'Papua New Guinea': 'PNG',
  'Trinidad and Tobago': 'Trinidad',
  'Timor-Leste': 'Timor',
};

function normalizeCountry(name) {
  if (!name) return null;
  const t = name.trim();
  return EVENT_COUNTRY_ALIASES[t] || t;
}

function shortCountryName(name) {
  if (SHORT_NAMES[name]) return SHORT_NAMES[name];
  if (name.length <= 14) return name;
  return name.replace(' and ', ' & ').slice(0, 14);
}

export function sevColor(s) {
  if (s >= 0.7) return '#ff2244';
  if (s >= 0.45) return '#ffaa00';
  return '#7a8a9a';
}

export const CAT_COLORS = {
  conflict: '#ff2244',
  unrest: '#ff7700',
  military: '#00aaff',
  diplomacy: '#00dd66',
  disaster: '#ffdd00',
  hazard: '#cc44ff',
  other: '#8899aa',
};

const CAT_SHAPES = {
  conflict: 'triangle',
  unrest: 'diamond',
  military: 'square',
  diplomacy: 'circle',
  disaster: 'star',
  hazard: 'cross',
  other: 'ring',
};

const ZONE_COLORS = { war: '#c44038', high: '#d4882a', elevated: '#b58a3a' };

export function catColor(category) {
  return CAT_COLORS[category] || CAT_COLORS.other;
}

const MARKER_PX = 24;
const MARKER_WORLD = 0.011;
const _symTexCache = new Map();

function drawEventShape(ctx, cx, cy, shape, hex) {
  ctx.fillStyle = hex;
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.lineWidth = 1.25;
  const stroke = () => { ctx.fill(); ctx.stroke(); };
  if (shape === 'triangle') {
    ctx.beginPath();
    ctx.moveTo(cx, cy - 8);
    ctx.lineTo(cx + 7, cy + 6);
    ctx.lineTo(cx - 7, cy + 6);
    ctx.closePath();
    stroke();
  } else if (shape === 'diamond') {
    ctx.beginPath();
    ctx.moveTo(cx, cy - 8);
    ctx.lineTo(cx + 8, cy);
    ctx.lineTo(cx, cy + 8);
    ctx.lineTo(cx - 8, cy);
    ctx.closePath();
    stroke();
  } else if (shape === 'square') {
    ctx.fillRect(cx - 7, cy - 7, 14, 14);
    ctx.strokeRect(cx - 7, cy - 7, 14, 14);
  } else if (shape === 'star') {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const a = (i * Math.PI) / 5 - Math.PI / 2;
      const rad = i % 2 ? 4 : 8;
      const x = cx + Math.cos(a) * rad;
      const y = cy + Math.sin(a) * rad;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
    stroke();
  } else if (shape === 'cross') {
    ctx.lineWidth = 3;
    ctx.strokeStyle = hex;
    ctx.beginPath();
    ctx.moveTo(cx - 7, cy); ctx.lineTo(cx + 7, cy);
    ctx.moveTo(cx, cy - 7); ctx.lineTo(cx, cy + 7);
    ctx.stroke();
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.55)';
    ctx.stroke();
  } else if (shape === 'ring') {
    ctx.beginPath();
    ctx.arc(cx, cy, 7, 0, Math.PI * 2);
    ctx.strokeStyle = hex;
    ctx.lineWidth = 3;
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.arc(cx, cy, 7, 0, Math.PI * 2);
    stroke();
  }
}

function eventDotTexture(category, high = false) {
  const cat = category in CAT_COLORS ? category : 'other';
  const key = `dot:${cat}:${high ? '1' : '0'}`;
  if (_symTexCache.has(key)) return _symTexCache.get(key);
  const hex = catColor(cat);
  const shape = CAT_SHAPES[cat] || 'circle';
  const canvas = document.createElement('canvas');
  const pad = high ? 5 : 3;
  canvas.width = MARKER_PX + pad * 2;
  canvas.height = MARKER_PX + pad * 2;
  const ctx = canvas.getContext('2d');
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  if (high) {
    ctx.beginPath();
    ctx.arc(cx, cy, 11, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255, 220, 60, 0.95)';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  drawEventShape(ctx, cx, cy, shape, hex);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  _symTexCache.set(key, tex);
  return tex;
}

function intelDotTexture(hex, shape = 'circle') {
  const key = `intel:${hex}:${shape}`;
  if (_symTexCache.has(key)) return _symTexCache.get(key);
  const canvas = document.createElement('canvas');
  canvas.width = 20;
  canvas.height = 20;
  const ctx = canvas.getContext('2d');
  const cx = 10, cy = 10;
  ctx.fillStyle = hex;
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1;
  if (shape === 'diamond') {
    ctx.beginPath();
    ctx.moveTo(cx, cy - 6);
    ctx.lineTo(cx + 6, cy);
    ctx.lineTo(cx, cy + 6);
    ctx.lineTo(cx - 6, cy);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  } else if (shape === 'square') {
    ctx.fillRect(cx - 5, cy - 5, 10, 10);
    ctx.strokeRect(cx - 5, cy - 5, 10, 10);
  } else if (shape === 'triangle') {
    ctx.beginPath();
    ctx.moveTo(cx, cy - 6);
    ctx.lineTo(cx + 6, cy + 5);
    ctx.lineTo(cx - 6, cy + 5);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.arc(cx, cy, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  _symTexCache.set(key, tex);
  return tex;
}

function zoneOutlineTexture(severity) {
  const key = `zone:${severity}`;
  if (_symTexCache.has(key)) return _symTexCache.get(key);
  const hex = ZONE_COLORS[severity] || ZONE_COLORS.elevated;
  const canvas = document.createElement('canvas');
  canvas.width = 36;
  canvas.height = 36;
  const ctx = canvas.getContext('2d');
  const cx = 18;
  const cy = 18;
  const r = 11;
  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx + r, cy);
  ctx.lineTo(cx, cy + r);
  ctx.lineTo(cx - r, cy);
  ctx.closePath();
  ctx.strokeStyle = hex;
  ctx.lineWidth = severity === 'war' ? 2.5 : 2;
  ctx.globalAlpha = 0.75;
  ctx.stroke();
  ctx.globalAlpha = 1;
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  _symTexCache.set(key, tex);
  return tex;
}

let _heatBlobTex = null;
function heatBlobTexture() {
  if (_heatBlobTex) return _heatBlobTex;
  const c = document.createElement('canvas');
  c.width = 128; c.height = 128;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, 'rgba(255, 255, 255, 1)');
  g.addColorStop(0.25, 'rgba(255, 255, 255, 0.55)');
  g.addColorStop(0.55, 'rgba(255, 255, 255, 0.15)');
  g.addColorStop(1, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  _heatBlobTex = new THREE.CanvasTexture(c);
  _heatBlobTex.colorSpace = THREE.SRGBColorSpace;
  return _heatBlobTex;
}

export function latLonToVec3(lat, lon, r) {
  const phi = (90 - lat) * Math.PI / 180;
  const theta = (lon + 180) * Math.PI / 180;
  return new THREE.Vector3(
    -r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta)
  );
}

// Direction of the point where the sun is overhead right now. Day side =
// hemisphere facing this vector. Uses the same lat/lon mapping as the globe,
// so no empirical offset is needed.
function subsolarDirection(date) {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const doy = (date.getTime() - start) / 86400000;
  const B = (2 * Math.PI * (doy - 81)) / 365;
  const declDeg = Math.asin(0.39779 * Math.sin(B)) * 180 / Math.PI;
  const eotMin = 9.87 * Math.sin(2 * B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B);
  const utcHours = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const subsolarLon = (12 - utcHours - eotMin / 60) * 15;
  return latLonToVec3(declDeg, subsolarLon, 1).normalize();
}

function ringCentroid(ring) {
  let area = 0, cx = 0, cy = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [x0, y0] = ring[i], [x1, y1] = ring[i + 1];
    const f = x0 * y1 - x1 * y0;
    area += f;
    cx += (x0 + x1) * f;
    cy += (y0 + y1) * f;
  }
  if (Math.abs(area) < 1e-9) return ring[0];
  area *= 0.5;
  return [cy / (6 * area), cx / (6 * area)]; // lat, lon
}

function featureCentroid(feature) {
  const polys = feature.geometry.type === 'Polygon'
    ? [feature.geometry.coordinates]
    : feature.geometry.coordinates;
  let best = null, bestLen = -1;
  for (const poly of polys) {
    const ring = poly[0];
    if (ring.length > bestLen) {
      best = ring;
      bestLen = ring.length;
    }
  }
  const [lat, lon] = ringCentroid(best);
  return [lat, lon];
}

function biomeGradient(ctx, H) {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  for (const [lat, color] of PALETTE.biomes) {
    g.addColorStop((90 - lat) / 180, color);
    g.addColorStop(1 - (90 - lat) / 180, color);
  }
  return g;
}

function paintOcean(ctx, W, H) {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, PALETTE.oceanDeep);
  g.addColorStop(0.2, '#082540');
  g.addColorStop(0.45, PALETTE.oceanTropic);
  g.addColorStop(0.55, PALETTE.oceanTropic);
  g.addColorStop(0.8, '#082540');
  g.addColorStop(1, PALETTE.oceanDeep);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // Subtle swell bands. Constant-latitude stripes turn into concentric
  // circles around the poles, so fade them out above |lat| 55° and use
  // wave frequencies that tile across the texture seam.
  const k1 = (2 * Math.PI * 4) / W;
  const k2 = (2 * Math.PI * 11) / W;
  for (let band = 0; band < 90; band++) {
    const y0 = (band / 90) * H;
    const lat = Math.abs(90 - (y0 / H) * 180);
    const fade = Math.min(1, Math.max(0, (75 - lat) / 20));
    if (fade <= 0.01) continue;
    ctx.globalAlpha = 0.07 * fade;
    ctx.strokeStyle = band % 2 ? '#5ec8f0' : '#1a5a8a';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let x = 0; x <= W; x += 16) {
      const y = y0 + Math.sin(x * k1 + band * 0.7) * 8 + Math.sin(x * k2) * 4;
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  ctx.globalAlpha = 0.035;
  for (let i = 0; i < 20000; i++) {
    const x = Math.random() * W, y = Math.random() * H;
    ctx.fillStyle = Math.random() < 0.5 ? '#90e0ff' : '#ffffff';
    ctx.fillRect(x, y, 1, 1);
  }
  ctx.globalAlpha = 1;
}

// Pseudo-edges introduced by the equirectangular cut: Antarctica's ring runs
// along lat −90 and up the antimeridian. Stroking them paints fake coastline
// that collapses into bullseye rings around the south pole (and a seam line).
function isPseudoEdge(a, b) {
  if (a[1] <= -89.5 && b[1] <= -89.5) return true;
  if (Math.abs(a[0]) >= 179.99 && Math.abs(b[0]) >= 179.99) return true;
  if (Math.abs(a[0] - b[0]) > 180) return true; // wraps the antimeridian
  return false;
}

// Net eastward travel in degrees; ±360 means the ring encircles a pole.
function ringWinding(ring) {
  let total = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    let d = ring[i + 1][0] - ring[i][0];
    if (d > 180) d -= 360; else if (d < -180) d += 360;
    total += d;
  }
  return total;
}

function drawCountryPaths(ctx, countriesGeo, px, { fill, stroke, lineWidth = 1.2 } = {}) {
  for (const f of countriesGeo.features) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) {
      ctx.beginPath();
      for (const ring of poly) {
        if (stroke && !fill) {
          let pen = false;
          for (let i = 0; i < ring.length - 1; i++) {
            const a = ring[i], b = ring[i + 1];
            if (isPseudoEdge(a, b)) { pen = false; continue; }
            const [x0, y0] = px(a[0], a[1]);
            const [x1, y1] = px(b[0], b[1]);
            if (!pen) { ctx.moveTo(x0, y0); pen = true; }
            ctx.lineTo(x1, y1);
          }
        } else {
          // Degenerate cap-edge ring (all points on the lat −90 cut): no area.
          if (ring.every((p) => p[1] <= -89.5)) continue;
          if (Math.abs(ringWinding(ring)) >= 350) {
            // Ring encircles a pole. Draw with unwrapped longitudes and close
            // along the pole edge of the map, otherwise the closing chord cuts
            // across and the polar cap is left unfilled (ocean bullseye).
            const south = ring[0][1] < 0;
            const poleLat = south ? -90 : 90;
            let lonU = ring[0][0];
            ring.forEach(([lon, lat], i) => {
              if (i > 0) {
                let d = lon - ring[i - 1][0];
                if (d > 180) d -= 360; else if (d < -180) d += 360;
                lonU += d;
              }
              const [x, y] = px(lonU, lat);
              i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            });
            const [xEnd, yPole] = px(lonU, poleLat);
            const [xStart] = px(ring[0][0], poleLat);
            ctx.lineTo(xEnd, yPole);
            ctx.lineTo(xStart, yPole);
            ctx.closePath();
          } else {
            ring.forEach(([lon, lat], i) => {
              const [x, y] = px(lon, lat);
              i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            });
            ctx.closePath();
          }
        }
      }
      if (fill) ctx.fill('evenodd');
      if (stroke) { ctx.lineWidth = lineWidth; ctx.stroke(); }
    }
  }
}

function buildTexture(countriesGeo) {
  const W = 4096, H = 2048;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  const px = (lon, lat) => [(lon + 180) / 360 * W, (90 - lat) / 180 * H];

  paintOcean(ctx, W, H);

  // Water-depth mask: 1.0 = deep ocean, 0.55 = shallow shelf, 0.0 = land
  const waterMask = document.createElement('canvas');
  waterMask.width = W; waterMask.height = H;
  const wctx = waterMask.getContext('2d');
  wctx.fillStyle = '#fff';
  wctx.fillRect(0, 0, W, H);

  // Shallow coastal shelf
  wctx.strokeStyle = 'rgb(140,140,140)';
  wctx.lineWidth = 10;
  wctx.lineJoin = 'round';
  drawCountryPaths(wctx, countriesGeo, px, { stroke: true, lineWidth: 10 });

  // Land mask cutout
  wctx.fillStyle = '#000';
  drawCountryPaths(wctx, countriesGeo, px, { fill: true });

  // Coastal tint on base map
  ctx.strokeStyle = 'rgba(48, 160, 190, 0.35)';
  ctx.lineWidth = 6;
  drawCountryPaths(ctx, countriesGeo, px, { stroke: true, lineWidth: 6 });

  // Land layer with biome fill
  const land = document.createElement('canvas');
  land.width = W; land.height = H;
  const lctx = land.getContext('2d');
  lctx.fillStyle = '#fff';
  drawCountryPaths(lctx, countriesGeo, px, { fill: true });
  lctx.globalCompositeOperation = 'source-in';
  lctx.fillStyle = biomeGradient(lctx, H);
  lctx.fillRect(0, 0, W, H);
  lctx.globalCompositeOperation = 'source-atop';
  for (let i = 0; i < 6000; i++) {
    const x = Math.random() * W, y = Math.random() * H;
    lctx.fillStyle = Math.random() < 0.5 ? 'rgba(0,30,0,0.04)' : 'rgba(255,240,200,0.04)';
    lctx.fillRect(x, y, 1 + Math.random() * 2, 1 + Math.random() * 2);
  }
  lctx.globalCompositeOperation = 'source-over';

  ctx.shadowColor = 'rgba(120, 200, 230, 0.35)';
  ctx.shadowBlur = 8;
  ctx.drawImage(land, 0, 0);
  ctx.shadowBlur = 0;

  ctx.strokeStyle = PALETTE.coast;
  ctx.lineWidth = 1.4;
  drawCountryPaths(ctx, countriesGeo, px, { stroke: true, lineWidth: 1.4 });

  ctx.strokeStyle = PALETTE.graticule;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let lon = -180; lon <= 180; lon += 30) {
    const x = (lon + 180) / 360 * W;
    ctx.moveTo(x, 0); ctx.lineTo(x, H);
  }
  ctx.stroke();

  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  // No mipmaps: the shader thresholds this mask, and mip averaging of
  // land (0) with ocean (1) at the poles reads as mid-gray "shallow shelf",
  // painting a turquoise bullseye over the polar caps.
  const waterTex = new THREE.CanvasTexture(waterMask);
  waterTex.colorSpace = THREE.NoColorSpace;
  waterTex.generateMipmaps = false;
  waterTex.minFilter = THREE.LinearFilter;
  waterTex.anisotropy = 8;
  return { map: tex, waterMap: waterTex };
}

function buildBorders(bordersMesh) {
  const positions = [];
  for (const line of bordersMesh.coordinates) {
    for (let i = 0; i < line.length - 1; i++) {
      const a = latLonToVec3(line[i][1], line[i][0], 1.002);
      const b = latLonToVec3(line[i + 1][1], line[i + 1][0], 1.002);
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.LineSegments(
    geo,
    new THREE.LineBasicMaterial({ color: PALETTE.border3d, transparent: true, opacity: 0.35 })
  );
}

function makeLabelSprite(text, { fontSize = 14, bold = false } = {}) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const font = `${bold ? 600 : 500} ${fontSize}px Inter, system-ui, sans-serif`;
  ctx.font = font;
  const tw = ctx.measureText(text).width;
  const pad = 3;
  canvas.width = Math.ceil(tw + pad * 2);
  canvas.height = Math.ceil(fontSize * 1.3 + pad * 2);
  ctx.font = font;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.strokeStyle = 'rgba(12, 10, 8, 0.92)';
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.strokeText(text, canvas.width / 2, canvas.height / 2);
  ctx.fillStyle = '#d8d0c4';
  ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({
    map: tex, transparent: true, depthTest: true, depthWrite: false, color: 0x9a9088,
  });
  const sprite = new THREE.Sprite(mat);
  sprite.userData = { type: 'country', aspect: canvas.width / canvas.height };
  return sprite;
}

function glowTexture(hex) {
  const c = document.createElement('canvas');
  c.width = 128; c.height = 128;
  const ctx = c.getContext('2d');
  const col = new THREE.Color(hex);
  const r = Math.round(col.r * 255), g = Math.round(col.g * 255), b = Math.round(col.b * 255);
  const grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, `rgba(${r},${g},${b},1)`);
  grad.addColorStop(0.4, `rgba(${r},${g},${b},0.35)`);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function createMarker(ev) {
  const group = new THREE.Group();
  const cat = ev.category || 'other';
  const high = ev.severity >= 0.7;

  const icon = new THREE.Sprite(new THREE.SpriteMaterial({
    map: eventDotTexture(cat, high), transparent: true, depthWrite: false,
  }));
  icon.scale.set(MARKER_WORLD, MARKER_WORLD, 1);
  group.add(icon);

  group.userData.event = ev;
  return group;
}

function createZoneMarker(zone) {
  const group = new THREE.Group();
  const icon = new THREE.Sprite(new THREE.SpriteMaterial({
    map: zoneOutlineTexture(zone.severity), transparent: true, depthWrite: false,
  }));
  icon.scale.set(MARKER_WORLD * 1.55, MARKER_WORLD * 1.55, 1);
  group.add(icon);

  group.userData.zone = zone;
  return group;
}

function subsolarLatLon(sunDir) {
  const s = sunDir.clone().normalize();
  const declDeg = Math.asin(THREE.MathUtils.clamp(s.y, -1, 1)) * 180 / Math.PI;
  const phi = (90 - declDeg) * Math.PI / 180;
  const sinPhi = Math.sin(phi);
  const theta = sinPhi > 1e-6 ? Math.atan2(s.z, -s.x) : 0;
  const lon = theta * 180 / Math.PI - 180;
  return { declRad: declDeg * Math.PI / 180, lon };
}

function terminatorPositions(sunDir, r = 1.006) {
  const { declRad, lon: subLon } = subsolarLatLon(sunDir);
  const positions = [];
  const lonStep = 2.5;
  for (let lon = -180; lon <= 180; lon += lonStep) {
    const ha = (lon - subLon) * Math.PI / 180;
    let latRad = 0;
    if (Math.abs(declRad) > 1e-4) {
      latRad = Math.atan(-Math.cos(ha) / Math.tan(declRad));
    }
    const latDeg = latRad * 180 / Math.PI;
    if (Math.abs(latDeg) > 89) continue;
    const p = latLonToVec3(latDeg, lon, r);
    positions.push(p.x, p.y, p.z);
  }
  return positions;
}

function buildTerminator(sunDir) {
  const positions = terminatorPositions(sunDir);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.Line(
    geo,
    new THREE.LineBasicMaterial({ color: 0xc9a227, transparent: true, opacity: 0.72, depthWrite: false })
  );
}

const GLOBE_VERT = `
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  void main() {
    vUv = uv;
    vNormal = normalize(mat3(modelMatrix) * normal);
    vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const GLOBE_FRAG = `
  uniform sampler2D map;
  uniform sampler2D waterMap;
  uniform vec3 sunDir;
  uniform vec3 cameraPos;
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  void main() {
    vec3 c = texture2D(map, vUv).rgb;
    float wm = texture2D(waterMap, vUv).r;
    float isWater = smoothstep(0.14, 0.32, wm);
    vec3 N = normalize(vNormal);
    float d = dot(N, sunDir);
    float day = smoothstep(-0.08, 0.18, d);
    vec3 viewDir = normalize(cameraPos - vWorldPos);

    vec3 landNight = c * vec3(0.32, 0.30, 0.28);
    vec3 landDay   = c * vec3(1.12, 1.06, 0.98);
    vec3 landCol = mix(landNight, landDay, day);
    float term = smoothstep(0.0, 0.08, d) * (1.0 - smoothstep(0.08, 0.25, d));
    landCol += vec3(0.22, 0.14, 0.05) * term * c * 1.6;

    float depth = wm;
    vec3 deepW  = vec3(0.01, 0.07, 0.20);
    vec3 midW   = vec3(0.04, 0.28, 0.50);
    vec3 shelfW = vec3(0.12, 0.52, 0.65);
    vec3 waterDay = mix(deepW, midW, smoothstep(0.3, 0.85, depth));
    waterDay = mix(waterDay, shelfW, smoothstep(0.14, 0.45, depth) * (1.0 - smoothstep(0.14, 0.45, depth) * 0.5));
    vec3 waterNight = vec3(0.005, 0.03, 0.10);
    vec3 waterCol = mix(waterNight, waterDay, day);

    vec3 refl = reflect(-sunDir, N);
    float spec = pow(max(dot(refl, viewDir), 0.0), 28.0) * day * isWater;
    waterCol += vec3(0.55, 0.82, 1.0) * spec * 0.45;

    vec3 col = mix(landCol, waterCol, isWater);

    float rim = pow(1.0 - max(dot(N, viewDir), 0.0), 2.5);
    col += mix(
      vec3(0.55, 0.42, 0.18) * 0.22,
      vec3(0.25, 0.55, 0.75) * 0.28,
      isWater
    ) * rim * smoothstep(-0.05, 0.2, d);

    gl_FragColor = vec4(col, 1.0);
  }`;

const ATMOS_FRAG = `
  uniform vec3 sunDir;
  uniform vec3 cameraPos;
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  void main() {
    vec3 N = normalize(vNormal);
    vec3 viewDir = normalize(cameraPos - vWorldPos);
    float viewDot = dot(N, viewDir);
    float sunDot = dot(N, sunDir);
    float rim = pow(1.0 - max(viewDot, 0.0), 4.0);
    float daySide = smoothstep(-0.1, 0.15, sunDot);
    vec3 color = mix(vec3(0.06, 0.08, 0.14), vec3(0.35, 0.60, 0.82), daySide);
    float intensity = rim * mix(0.04, 0.16, daySide);
    gl_FragColor = vec4(color, intensity);
  }`;

export class Globe {
  constructor(container, { onHover, onSelect, onZoneHover, onZoneSelect } = {}) {
    this.container = container;
    this.onHover = onHover || (() => {});
    this.onSelect = onSelect || (() => {});
    this.onZoneHover = onZoneHover || (() => {});
    this.onZoneSelect = onZoneSelect || (() => {});
    this.markers = new THREE.Group();
    this.zones = new THREE.Group();
    this.heatmap = new THREE.Group();
    this.flights = new THREE.Group();
    this.vessels = new THREE.Group();
    this.fires = new THREE.Group();
    this.satellites = new THREE.Group();
    this.osintPin = new THREE.Group();
    this.labels = new THREE.Group();
    this._labelIndex = new Map();
    this._eventCountries = new Set();
    this._proj = new THREE.Vector3();
    this.selectedId = null;
    this.labelsVisible = true;
    this.eventsVisible = true;
    this.zonesVisible = true;
    this.heatmapVisible = false;
    this.flightsVisible = false;
    this.vesselsVisible = false;
    this.firesVisible = false;
    this.satellitesVisible = false;
    this.photoEarth = false;
    this._globeMat = null;
    this._proceduralMap = null;
    this._proceduralWater = null;
    this.dayNightVisible = true;
    this.liveSun = true;
    this._frozenSun = subsolarDirection(new Date());
    this._terminator = null;
    this._flyAnim = null;
    this._selRing = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x060a10);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
    const sun = subsolarDirection(new Date());
    const anchors = [[28, -95], [30, 15], [30, 95]];
    const best = anchors
      .map(([lat, lon]) => ({ v: latLonToVec3(lat, lon, 1), d: latLonToVec3(lat, lon, 1).dot(sun) }))
      .sort((a, b) => b.d - a.d)[0].v;
    this.camera.position.copy(best.multiplyScalar(2.8));

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.rotateSpeed = 0.5;
    this.controls.minDistance = 1.3;
    this.controls.maxDistance = 5.5;
    this.controls.enablePan = false;
    this.controls.minPolarAngle = 0.15;
    this.controls.maxPolarAngle = Math.PI - 0.15;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.15;
    this.controls.addEventListener('start', () => { this.controls.autoRotate = false; });

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._hovered = null;

    this.renderer.domElement.addEventListener('pointermove', (e) => this._onPointerMove(e));
    this.renderer.domElement.addEventListener('click', (e) => this._onClick(e));
    window.addEventListener('resize', () => this._resize());
    this._resize();
  }

  async init() {
    const topo = await (await fetch('/data/countries-50m.json')).json();
    const countries = topojson.feature(topo, topo.objects.countries);
    const borders = topojson.mesh(topo, topo.objects.countries);

    this.sunUniform = { value: subsolarDirection(new Date()) };
    this.camUniform = { value: this.camera.position.clone() };
    const { map, waterMap } = buildTexture(countries);
    this._proceduralMap = map;
    this._proceduralWater = waterMap;
    this._globeMat = new THREE.ShaderMaterial({
      uniforms: {
        map: { value: map }, waterMap: { value: waterMap },
        sunDir: this.sunUniform, cameraPos: this.camUniform,
      },
      vertexShader: GLOBE_VERT,
      fragmentShader: GLOBE_FRAG,
    });
    this._globeMesh = new THREE.Mesh(new THREE.SphereGeometry(1, 128, 96), this._globeMat);
    // Fix pole UVs to eliminate bullseye ring artifacts at the poles.
    // Standard SphereGeometry sets UV.y=0 at the north pole, creating a sharp
    // UV gradient across the polar triangle-fan that renders as concentric rings.
    // Nudge to match the adjacent latitudinal ring — no mid-latitude vertices
    // are touched, so no green smear.
    (function fixPoleUVs(geo) {
      const pos = geo.attributes.position;
      const uv = geo.attributes.uv;
      const hSegs = 96;
      const eps = 1 / hSegs;
      for (let i = 0; i < pos.count; i++) {
        const y = pos.getY(i);
        if (y > 0.999) {
          uv.setY(i, eps);
        } else if (y < -0.999) {
          uv.setY(i, 1 - eps);
        }
      }
      uv.needsUpdate = true;
    })(this._globeMesh.geometry);
    this.scene.add(this._globeMesh);

    // Offline photo earth (bundled 2K texture)
    try {
      const loader = new THREE.TextureLoader();
      const photo = await new Promise((resolve, reject) => {
        loader.load('/data/textures/earth-day-2k.jpg', resolve, undefined, reject);
      });
      photo.colorSpace = THREE.SRGBColorSpace;
      photo.anisotropy = 8;
      this._photoMap = photo;
    } catch {
      this._photoMap = null;
    }

    const atmosMat = new THREE.ShaderMaterial({
      uniforms: { sunDir: this.sunUniform, cameraPos: this.camUniform },
      vertexShader: GLOBE_VERT,
      fragmentShader: ATMOS_FRAG,
      transparent: true, depthWrite: false, side: THREE.BackSide,
    });
    this.scene.add(new THREE.Mesh(new THREE.SphereGeometry(1.018, 96, 72), atmosMat));
    this.scene.add(buildBorders(borders));

    const starPos = [];
    const starSizes = [];
    for (let i = 0; i < 1800; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(40 + Math.random() * 25);
      starPos.push(v.x, v.y, v.z);
      starSizes.push(0.03 + Math.random() * 0.05);
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute('position', new THREE.Float32BufferAttribute(starPos, 3));
    this.scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({
      color: 0x6a6058, size: 0.05, sizeAttenuation: true, transparent: true, opacity: 0.55,
    })));

    this._buildLabels(countries);
    this._terminator = buildTerminator(this.sunUniform.value);
    this.scene.add(this._terminator);
    this.scene.add(this.labels);
    this.scene.add(this.heatmap);
    this.scene.add(this.fires);
    this.scene.add(this.flights);
    this.scene.add(this.vessels);
    this.scene.add(this.satellites);
    this.scene.add(this.osintPin);
    this.scene.add(this.zones);
    this.scene.add(this.markers);
    this._clock = new THREE.Clock();
    this.renderer.setAnimationLoop(() => this._tick());
  }

  setConflictZones(zones) {
    for (const child of [...this.zones.children]) {
      child.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          if (o.material.map) o.material.map.dispose();
          o.material.dispose();
        }
      });
      this.zones.remove(child);
    }
    for (const zone of zones) {
      const group = createZoneMarker(zone);
      const pos = latLonToVec3(zone.lat, zone.lon, 1.002);
      group.position.copy(pos);
      group.renderOrder = 0;
      this.zones.add(group);
    }
  }

  setHeatmap(points) {
    for (const child of [...this.heatmap.children]) {
      if (child.material?.map) child.material.map.dispose();
      child.material?.dispose();
      this.heatmap.remove(child);
    }
    const tex = heatBlobTexture();
    for (const p of points) {
      const t = Math.min(1, p.intensity);
      const col = new THREE.Color('#3a1868').lerp(new THREE.Color('#c82848'), t);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, color: col, transparent: true,
        opacity: 0.18 + t * 0.28,
        depthWrite: false, depthTest: true,
      }));
      const size = 0.06 + t * 0.14 + Math.min(p.count || 1, 12) * 0.008;
      sprite.scale.set(size, size, 1);
      const pos = latLonToVec3(p.lat, p.lon, 1.001);
      sprite.position.copy(pos);
      sprite.renderOrder = -1;
      this.heatmap.add(sprite);
    }
  }

  setPhotoEarth(on) {
    this.photoEarth = !!on;
    if (!this._globeMat) return;
    const map = (on && this._photoMap) ? this._photoMap : this._proceduralMap;
    if (map) this._globeMat.uniforms.map.value = map;
  }

  _setIntelGroup(group, items, { color, shape, r = 1.003, size = 0.006 }) {
    for (const child of [...group.children]) {
      if (child.material?.map) child.material.map.dispose();
      child.material?.dispose();
      group.remove(child);
    }
    const tex = intelDotTexture(color, shape);
    for (const item of items) {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, transparent: true, depthWrite: false, color: 0xffffff,
      }));
      sprite.scale.set(size, size, 1);
      sprite.position.copy(latLonToVec3(item.lat, item.lon, r));
      sprite.userData.intel = item;
      group.add(sprite);
    }
  }

  setFlights(items) {
    this._setIntelGroup(this.flights, items, { color: '#38b0d8', shape: 'diamond', size: 0.005 });
  }

  setVessels(items) {
    this._setIntelGroup(this.vessels, items, { color: '#2a88c8', shape: 'triangle', size: 0.006 });
  }

  setOsintPin(pin) {
    for (const child of [...this.osintPin.children]) {
      if (child.material?.map) child.material.map.dispose();
      child.material?.dispose();
      this.osintPin.remove(child);
    }
    if (!pin || pin.lat == null || pin.lon == null) return;
    const tex = intelDotTexture('#ff40a0', 'diamond');
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, depthWrite: false, color: 0xffffff,
    }));
    sprite.scale.set(0.012, 0.012, 1);
    sprite.position.copy(latLonToVec3(pin.lat, pin.lon, 1.004));
    sprite.userData.osint = pin;
    this.osintPin.add(sprite);
  }

  setFires(items) {
    this._setIntelGroup(this.fires, items, { color: '#ff6020', shape: 'circle', size: 0.007 });
  }

  setSatellites(items) {
    this._setIntelGroup(this.satellites, items, { color: '#e8e040', shape: 'square', size: 0.009 });
  }

  setLayers({ events, zones, heatmap, flights, vessels, fires, satellites, photoEarth,
                labels, dayNight, liveSun, autoRotate } = {}) {
    if (events !== undefined) {
      this.eventsVisible = events;
      this.markers.visible = events;
    }
    if (zones !== undefined) {
      this.zonesVisible = zones;
      this.zones.visible = zones;
    }
    if (heatmap !== undefined) {
      this.heatmapVisible = heatmap;
      this.heatmap.visible = heatmap;
    }
    if (flights !== undefined) {
      this.flightsVisible = flights;
      this.flights.visible = flights;
    }
    if (vessels !== undefined) {
      this.vesselsVisible = vessels;
      this.vessels.visible = vessels;
    }
    if (fires !== undefined) {
      this.firesVisible = fires;
      this.fires.visible = fires;
    }
    if (satellites !== undefined) {
      this.satellitesVisible = satellites;
      this.satellites.visible = satellites;
    }
    if (photoEarth !== undefined) this.setPhotoEarth(photoEarth);
    if (labels !== undefined) this.setLabelsVisible(labels);
    if (dayNight !== undefined) {
      this.dayNightVisible = dayNight;
      if (this._terminator) this._terminator.visible = dayNight;
    }
    if (liveSun !== undefined) {
      this.liveSun = liveSun;
      if (!liveSun) this._frozenSun = subsolarDirection(new Date());
    }
    if (autoRotate !== undefined) this.controls.autoRotate = autoRotate;
  }

  _buildLabels(countriesGeo) {
    for (const f of countriesGeo.features) {
      const name = f.properties?.name;
      if (!name) continue;
      const [lat, lon] = featureCentroid(f);
      const sprite = makeLabelSprite(shortCountryName(name), { fontSize: 13 });
      sprite.position.copy(latLonToVec3(lat, lon, 1.016));
      sprite.userData.countryName = name;
      sprite.userData.hasEvent = false;
      this.labels.add(sprite);
      this._labelIndex.set(name, sprite);
    }
  }

  _labelScale(dist) {
    const ref = 2.8;
    return Math.min(0.022, 0.008 * (ref / dist));
  }

  _labelScreenBox(sprite, h) {
    this._proj.copy(sprite.position).project(this.camera);
    if (this._proj.z > 1) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const px = (this._proj.x * 0.5 + 0.5) * rect.width;
    const py = (-this._proj.y * 0.5 + 0.5) * rect.height;
    const aspect = sprite.userData.aspect || 1;
    const d = this.camera.position.distanceTo(sprite.position);
    const screenH = Math.max(8, (h / d) * rect.height * 0.42);
    const screenW = screenH * aspect;
    return { x: px, y: py, w: screenW + 6, h: screenH + 4 };
  }

  _boxesOverlap(a, b) {
    return Math.abs(a.x - b.x) < (a.w + b.w) * 0.5
      && Math.abs(a.y - b.y) < (a.h + b.h) * 0.5;
  }

  _updateEventCountries(events) {
    this._eventCountries.clear();
    for (const ev of events) {
      const canon = normalizeCountry(ev.country);
      if (canon) this._eventCountries.add(canon);
      // Also try matching via place field last segment
      if (ev.place) {
        const last = ev.place.split(',').pop()?.trim();
        const fromPlace = normalizeCountry(last);
        if (fromPlace && this._labelIndex.has(fromPlace)) {
          this._eventCountries.add(fromPlace);
        }
      }
    }
    for (const [name, sprite] of this._labelIndex) {
      sprite.userData.hasEvent = this._eventCountries.has(name);
    }
  }

  setLabelsVisible(v) {
    this.labelsVisible = v;
    this.labels.visible = v;
  }

  setEvents(events) {
    for (const child of [...this.markers.children]) {
      child.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
      this.markers.remove(child);
    }
    this._updateEventCountries(events);

    for (const ev of events) {
      const group = createMarker(ev);
      const pos = latLonToVec3(ev.lat, ev.lon, 1.006);
      group.position.copy(pos);
      group.lookAt(pos.clone().multiplyScalar(2));
      group.renderOrder = 2;
      this.markers.add(group);
    }
    this.setSelected(this.selectedId);
  }

  setSelected(id) {
    this.selectedId = id;
    for (const g of this.markers.children) {
      const ev = g.userData.event;
      if (!ev) continue;
      const sel = ev.id === id;
      if (sel) {
        const icon = g.children[0];
        if (icon?.isSprite) icon.scale.set(MARKER_WORLD * 1.28, MARKER_WORLD * 1.28, 1);
      } else {
        const icon = g.children[0];
        if (icon?.isSprite) icon.scale.set(MARKER_WORLD, MARKER_WORLD, 1);
      }
    }
  }

  flyTo(lat, lon) {
    this.controls.autoRotate = false;
    const dist = Math.min(this.camera.position.length(), 2.2);
    const from = this.camera.position.clone().normalize();
    const to = latLonToVec3(lat, lon, 1).normalize();
    const qFrom = new THREE.Quaternion();
    const qTo = new THREE.Quaternion().setFromUnitVectors(from, to);
    this._flyAnim = { qFrom, qTo, from, dist, t0: performance.now(), dur: 900 };
  }

  _tick() {
    if (this._flyAnim) {
      const a = this._flyAnim;
      const t = Math.min((performance.now() - a.t0) / a.dur, 1);
      const e = 1 - Math.pow(1 - t, 3);
      const q = a.qFrom.clone().slerp(a.qTo, e);
      this.camera.position.copy(a.from.clone().applyQuaternion(q).setLength(a.dist));
      if (t >= 1) this._flyAnim = null;
    }
    this.controls.update();
    const sun = this.liveSun ? subsolarDirection(new Date()) : this._frozenSun;
    if (this.sunUniform) this.sunUniform.value = sun;
    if (this._terminator) {
      const pts = terminatorPositions(sun);
      this._terminator.geometry.setAttribute(
        'position',
        new THREE.BufferAttribute(new Float32Array(pts), 3)
      );
      this._terminator.visible = this.dayNightVisible;
    }
    this.camUniform && this.camUniform.value.copy(this.camera.position);

    const dist = this.camera.position.length();
    const screenScale = Math.min(Math.max(0.009 * (2.6 / dist), 0.007), 0.016) / MARKER_WORLD;

    for (const g of this.zones.children) {
      if (!g.userData.zone) continue;
      g.scale.setScalar(screenScale);
    }

    for (const g of this.markers.children) {
      if (!g.userData.event) continue;
      g.scale.setScalar(screenScale);
      const icon = g.children[0];
      const sel = g.userData.event.id === this.selectedId;
      if (icon?.isSprite) {
        const s = sel ? MARKER_WORLD * 1.28 : MARKER_WORLD;
        icon.scale.set(s, s, 1);
      }
    }

    if (this.labelsVisible) {
      const dist = this.camera.position.length();
      const baseH = this._labelScale(dist);
      const camDir = this.camera.position.clone().normalize();
      const candidates = [];

      for (const s of this.labels.children) {
        const facing = s.position.clone().normalize().dot(camDir);
        if (facing < 0.1) { s.visible = false; continue; }
        candidates.push({ sprite: s, facing, hasEvent: !!s.userData.hasEvent });
      }

      // Event countries first, then by how face-on they are to the camera
      candidates.sort((a, b) => (b.hasEvent - a.hasEvent) || (b.facing - a.facing));

      const placed = [];
      const showAll = dist < 1.85; // zoomed in: label every facing country
      for (const { sprite: s, facing, hasEvent } of candidates) {
        const h = hasEvent ? baseH * 1.12 : baseH * (dist < 1.9 ? 1 : dist < 2.4 ? 0.92 : 0.8);
        const box = this._labelScreenBox(s, h);
        if (!box) { s.visible = false; continue; }

        let blocked = false;
        if (!showAll) {
          for (const p of placed) {
            if (this._boxesOverlap(box, p)) {
              // Event countries always show; others hide when crowded
              if (!hasEvent) { blocked = true; break; }
            }
          }
        }

        if (blocked) { s.visible = false; continue; }

        placed.push({ ...box, hasEvent });
        s.visible = true;
        const aspect = s.userData.aspect || 1;
        s.scale.set(h * aspect, h, 1);
        s.material.color.setHex(hasEvent ? 0xe8dcc8 : 0x8a8278);
        s.material.opacity = hasEvent
          ? Math.min(1, 0.55 + facing * 0.45)
          : Math.min(0.9, 0.3 + facing * 0.55);
      }
    }

    this.renderer.render(this.scene, this.camera);
  }

  _pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const order = [
      { children: this.markers.children, key: 'event', visible: this.eventsVisible },
      { children: this.zones.children, key: 'zone', visible: this.zonesVisible },
    ];
    for (const { children, key, visible } of order) {
      if (!visible || !children.length) continue;
      const hits = this.raycaster.intersectObjects(children, true);
      for (const h of hits) {
        let o = h.object;
        while (o && !o.userData[key]) o = o.parent;
        if (o?.userData[key]) return { type: key, data: o.userData[key] };
      }
    }
    return null;
  }

  _onPointerMove(e) {
    const hit = this._pick(e);
    const ev = hit?.type === 'event' ? hit.data : null;
    const zone = hit?.type === 'zone' ? hit.data : null;
    if (ev !== this._hovered) {
      this._hovered = ev;
      this.renderer.domElement.style.cursor = hit ? 'pointer' : 'grab';
    }
    this.onHover(ev, e.clientX, e.clientY);
    this.onZoneHover(zone, e.clientX, e.clientY);
  }

  _onClick(e) {
    const hit = this._pick(e);
    if (!hit) return;
    if (hit.type === 'event') this.onSelect(hit.data);
    else if (hit.type === 'zone') this.onZoneSelect(hit.data);
  }

  _resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }
}