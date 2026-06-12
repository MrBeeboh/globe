/* Professional globe renderer: procedural basemap, atmosphere, labels, event markers. */
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const PALETTE = {
  ocean: '#243028',
  oceanDeep: '#121a16',
  coast: 'rgba(200, 185, 155, 0.55)',
  graticule: 'rgba(220, 200, 170, 0.05)',
  border3d: 0xd8ccb8,
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
  if (s >= 0.7) return '#c44038';
  if (s >= 0.45) return '#d4882a';
  return '#b58a3a';
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

function subsolarDirection(date) {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const doy = (date.getTime() - start) / 86400000;
  const decl = -23.44 * Math.cos(2 * Math.PI * (doy + 10) / 365.25) * Math.PI / 180;
  const utcHours = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const ha = (utcHours - 12) * 15 * Math.PI / 180 + Math.PI;
  const x = Math.cos(decl) * Math.cos(ha);
  const y = Math.sin(decl);
  const z = Math.cos(decl) * Math.sin(ha);
  return new THREE.Vector3(-x, -y, -z).normalize();
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

function buildTexture(countriesGeo) {
  const W = 4096, H = 2048;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');

  const og = ctx.createLinearGradient(0, 0, 0, H);
  og.addColorStop(0, PALETTE.oceanDeep);
  og.addColorStop(0.45, PALETTE.ocean);
  og.addColorStop(0.55, PALETTE.ocean);
  og.addColorStop(1, PALETTE.oceanDeep);
  ctx.fillStyle = og;
  ctx.fillRect(0, 0, W, H);

  ctx.strokeStyle = PALETTE.graticule;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let lon = -180; lon <= 180; lon += 30) {
    const x = (lon + 180) / 360 * W;
    ctx.moveTo(x, 0); ctx.lineTo(x, H);
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const y = (90 - lat) / 180 * H;
    ctx.moveTo(0, y); ctx.lineTo(W, y);
  }
  ctx.stroke();

  const px = (lon, lat) => [(lon + 180) / 360 * W, (90 - lat) / 180 * H];

  const land = document.createElement('canvas');
  land.width = W; land.height = H;
  const lctx = land.getContext('2d');
  lctx.fillStyle = '#fff';
  for (const f of countriesGeo.features) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) {
      lctx.beginPath();
      for (const ring of poly) {
        ring.forEach(([lon, lat], i) => {
          const [x, y] = px(lon, lat);
          i === 0 ? lctx.moveTo(x, y) : lctx.lineTo(x, y);
        });
        lctx.closePath();
      }
      lctx.fill('evenodd');
    }
  }
  lctx.globalCompositeOperation = 'source-in';
  lctx.fillStyle = biomeGradient(lctx, H);
  lctx.fillRect(0, 0, W, H);
  lctx.globalCompositeOperation = 'source-atop';
  for (let i = 0; i < 8000; i++) {
    const x = Math.random() * W, y = Math.random() * H;
    lctx.fillStyle = Math.random() < 0.5 ? 'rgba(0,30,0,0.04)' : 'rgba(255,240,200,0.04)';
    lctx.fillRect(x, y, 1 + Math.random() * 2, 1 + Math.random() * 2);
  }
  lctx.globalCompositeOperation = 'source-over';

  ctx.shadowColor = 'rgba(180, 155, 110, 0.45)';
  ctx.shadowBlur = 10;
  ctx.drawImage(land, 0, 0);
  ctx.shadowBlur = 0;
  ctx.strokeStyle = PALETTE.coast;
  ctx.lineWidth = 1.2;
  for (const f of countriesGeo.features) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) {
      ctx.beginPath();
      for (const ring of poly) {
        ring.forEach(([lon, lat], i) => {
          const [x, y] = px(lon, lat);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
      }
      ctx.stroke();
    }
  }

  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
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
  const hex = sevColor(ev.severity);
  const color = new THREE.Color(hex);
  const isHigh = ev.severity >= 0.7;
  const isMed = ev.severity >= 0.45;
  const base = 0.006 + ev.severity * 0.014;

  const glowMat = new THREE.SpriteMaterial({
    map: glowTexture(hex), transparent: true, opacity: 0.85,
    depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const glow = new THREE.Sprite(glowMat);
  glow.scale.set(base * 4, base * 4, 1);
  group.add(glow);

  const coreMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 1, depthWrite: false });
  const core = new THREE.Mesh(new THREE.CircleGeometry(base * 0.6, 16), coreMat);
  group.add(core);

  const ringMat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: isHigh ? 0.8 : 0.5,
    side: THREE.DoubleSide, depthWrite: false,
  });
  const ring = new THREE.Mesh(new THREE.RingGeometry(base * 0.9, base * 1.15, 24), ringMat);
  group.add(ring);

  if (isHigh || isMed) {
    const outerMat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0,
      side: THREE.DoubleSide, depthWrite: false,
    });
    const outer = new THREE.Mesh(new THREE.RingGeometry(base * 1.2, base * 1.35, 24), outerMat);
    group.add(outer);
    group.userData.outer = outer;
  }

  group.userData.event = ev;
  group.userData.base = base;
  group.userData.phase = Math.random() * Math.PI * 2;
  group.userData.speed = isHigh ? 2.5 : isMed ? 1.8 : 1.2;
  return group;
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
  uniform vec3 sunDir;
  uniform vec3 cameraPos;
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  void main() {
    vec3 c = texture2D(map, vUv).rgb;
    vec3 N = normalize(vNormal);
    float d = dot(N, sunDir);
    float day = smoothstep(-0.08, 0.18, d);
    vec3 night = c * vec3(0.32, 0.30, 0.28);
    vec3 dayC  = c * vec3(1.12, 1.06, 0.98);
    vec3 col = mix(night, dayC, day);
    float term = smoothstep(0.0, 0.08, d) * (1.0 - smoothstep(0.08, 0.25, d));
    col += vec3(0.22, 0.14, 0.05) * term * c * 1.6;
    vec3 viewDir = normalize(cameraPos - vWorldPos);
    float rim = pow(1.0 - max(dot(N, viewDir), 0.0), 2.5);
    col += vec3(0.55, 0.42, 0.18) * rim * 0.22 * smoothstep(-0.05, 0.2, d);
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
    vec3 color = mix(vec3(0.12, 0.10, 0.08), vec3(0.55, 0.42, 0.22), daySide);
    float intensity = rim * mix(0.04, 0.14, daySide);
    gl_FragColor = vec4(color, intensity);
  }`;

export class Globe {
  constructor(container, { onHover, onSelect } = {}) {
    this.container = container;
    this.onHover = onHover || (() => {});
    this.onSelect = onSelect || (() => {});
    this.markers = new THREE.Group();
    this.labels = new THREE.Group();
    this._labelIndex = new Map();
    this._eventCountries = new Set();
    this._proj = new THREE.Vector3();
    this.selectedId = null;
    this.labelsVisible = true;
    this._flyAnim = null;
    this._selRing = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0c0b09);

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
    const globeMat = new THREE.ShaderMaterial({
      uniforms: { map: { value: buildTexture(countries) }, sunDir: this.sunUniform, cameraPos: this.camUniform },
      vertexShader: GLOBE_VERT,
      fragmentShader: GLOBE_FRAG,
    });
    this.scene.add(new THREE.Mesh(new THREE.SphereGeometry(1, 128, 96), globeMat));

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
    this.scene.add(this.labels);
    this.scene.add(this.markers);
    this._clock = new THREE.Clock();
    this.renderer.setAnimationLoop(() => this._tick());
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
        if (o.material) {
          if (o.material.map) o.material.map.dispose();
          o.material.dispose();
        }
      });
      this.markers.remove(child);
    }
    if (this._selRing) {
      this._selRing.geometry.dispose();
      this._selRing.material.dispose();
      this.markers.remove(this._selRing);
      this._selRing = null;
    }

    this._updateEventCountries(events);

    for (const ev of events) {
      const group = createMarker(ev);
      const pos = latLonToVec3(ev.lat, ev.lon, 1.005);
      group.position.copy(pos);
      group.lookAt(pos.clone().multiplyScalar(2));
      group.renderOrder = 2;
      this.markers.add(group);
    }
    this.setSelected(this.selectedId);
  }

  setSelected(id) {
    this.selectedId = id;
    if (this._selRing) {
      this._selRing.geometry.dispose();
      this._selRing.material.dispose();
      this.markers.remove(this._selRing);
      this._selRing = null;
    }
    for (const g of this.markers.children) {
      const ev = g.userData.event;
      if (!ev) continue;
      const sel = ev.id === id;
      g.children.forEach((c) => {
        if (c.material) c.material.opacity = sel ? 1 : (c === g.children[0] ? 0.85 : c.material.opacity);
      });
      if (sel) {
        const pos = latLonToVec3(ev.lat, ev.lon, 1.008);
        this._selRing = new THREE.Mesh(
          new THREE.RingGeometry(0.022, 0.028, 32),
          new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false })
        );
        this._selRing.position.copy(pos);
        this._selRing.lookAt(pos.clone().multiplyScalar(2));
        this._selRing.renderOrder = 3;
        this.markers.add(this._selRing);
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
    const sun = subsolarDirection(new Date());
    this.sunUniform && (this.sunUniform.value = sun);
    this.camUniform && this.camUniform.value.copy(this.camera.position);

    const zoomScale = Math.min(Math.max((this.camera.position.length() - 1) / 1.8, 0.15), 1);
    const t = this._clock.getElapsedTime();

    for (const g of this.markers.children) {
      if (!g.userData.event) continue;
      g.scale.setScalar(zoomScale);
      const phase = t * g.userData.speed + g.userData.phase;
      if (g.userData.outer) {
        const pulse = (Math.sin(phase) + 1) * 0.5;
        g.userData.outer.material.opacity = pulse * 0.4;
        g.userData.outer.scale.setScalar(1 + pulse * 0.6);
      }
      const ring = g.children[2];
      if (ring?.material) ring.material.opacity = 0.4 + Math.sin(phase * 1.5) * 0.2;
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
    const hits = this.raycaster.intersectObjects(this.markers.children, true);
    for (const h of hits) {
      let o = h.object;
      while (o && !o.userData.event) o = o.parent;
      if (o?.userData.event) return o.userData.event;
    }
    return null;
  }

  _onPointerMove(e) {
    const ev = this._pick(e);
    if (ev !== this._hovered) {
      this._hovered = ev;
      this.renderer.domElement.style.cursor = ev ? 'pointer' : 'grab';
    }
    this.onHover(ev, e.clientX, e.clientY);
  }

  _onClick(e) {
    const ev = this._pick(e);
    if (ev) this.onSelect(ev);
  }

  _resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }
}