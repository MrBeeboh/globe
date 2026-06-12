/* Professional globe renderer: procedural basemap, atmosphere, labels, event markers. */
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const PALETTE = {
  ocean: '#1a4a7a',
  oceanDeep: '#0c2848',
  coast: 'rgba(200, 230, 255, 0.7)',
  graticule: 'rgba(255, 255, 255, 0.06)',
  border3d: 0xc8dce8,
  biomes: [
    [90, '#e8eef2'], [74, '#d0dde0'], [66, '#7a9a7c'], [58, '#3d6b3a'],
    [46, '#4a7a42'], [36, '#8a9a52'], [27, '#b8a070'], [20, '#c4a060'],
    [12, '#6a9a50'], [4, '#3d7a3a'], [0, '#357a38'],
  ],
};

const MAJOR_COUNTRIES = new Set([
  'United States of America', 'China', 'Russia', 'India', 'Brazil',
  'Indonesia', 'Nigeria', 'Japan', 'Germany', 'United Kingdom',
  'France', 'Mexico', 'Iran', 'Turkey', 'Saudi Arabia', 'Egypt',
  'South Africa', 'Pakistan', 'Ukraine', 'Israel', 'Palestine',
]);

const NEWS_CITIES = [
  ['Kyiv', 50.45, 30.52], ['Gaza', 31.50, 34.47], ['Moscow', 55.76, 37.62],
  ['Beirut', 33.89, 35.50], ['Tehran', 35.69, 51.39], ['Kabul', 34.55, 69.21],
  ['Beijing', 39.90, 116.40], ['Taipei', 25.03, 121.57], ['Seoul', 37.57, 126.98],
  ['Tokyo', 35.68, 139.69], ['Khartoum', 15.50, 32.56], ['Nairobi', -1.29, 36.82],
  ['Kinshasa', -4.32, 15.31], ['Lagos', 6.52, 3.38], ['Cairo', 30.04, 31.24],
  ['Riyadh', 24.71, 46.68], ['Istanbul', 41.01, 28.98], ['London', 51.51, -0.13],
  ['Washington', 38.91, -77.04], ['New York', 40.71, -74.01],
  ['Port-au-Prince', 18.54, -72.34], ['Caracas', 10.49, -66.88],
  ['Tbilisi', 41.72, 44.79], ['Damascus', 33.51, 36.29],
];

export function sevColor(s) {
  if (s >= 0.7) return '#ff5544';
  if (s >= 0.45) return '#ffaa22';
  return '#c9a227';
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

function featureCentroid(feature) {
  const coords = feature.geometry.type === 'Polygon'
    ? feature.geometry.coordinates[0]
    : feature.geometry.coordinates[0][0];
  let sx = 0, sy = 0;
  for (const [lon, lat] of coords) { sx += lon; sy += lat; }
  return [sy / coords.length, sx / coords.length];
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

  ctx.shadowColor = 'rgba(160, 210, 255, 0.6)';
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

function makeLabelSprite(text, fontSize, color, bgColor) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
  const tw = ctx.measureText(text).width;
  const padX = fontSize * 0.5, padY = fontSize * 0.25;
  canvas.width = Math.ceil(tw + padX * 2);
  canvas.height = Math.ceil(fontSize * 1.5 + padY * 2);
  ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  if (bgColor) {
    const bw = tw + padX, bh = fontSize * 1.3 + padY;
    ctx.fillStyle = bgColor;
    ctx.beginPath();
    ctx.roundRect(canvas.width / 2 - bw / 2, canvas.height / 2 - bh / 2, bw, bh, 4);
    ctx.fill();
  }
  ctx.fillStyle = color;
  ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true, depthWrite: false });
  const sprite = new THREE.Sprite(mat);
  const aspect = canvas.width / canvas.height;
  const h = 0.07;
  sprite.scale.set(h * aspect, h, 1);
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
    vec3 night = c * vec3(0.35, 0.38, 0.52);
    vec3 dayC  = c * vec3(1.15, 1.10, 1.02);
    vec3 col = mix(night, dayC, day);
    float term = smoothstep(0.0, 0.08, d) * (1.0 - smoothstep(0.08, 0.25, d));
    col += vec3(0.18, 0.10, 0.03) * term * c * 1.8;
    vec3 viewDir = normalize(cameraPos - vWorldPos);
    float rim = pow(1.0 - max(dot(N, viewDir), 0.0), 2.5);
    col += vec3(0.25, 0.50, 0.95) * rim * 0.35 * smoothstep(-0.05, 0.2, d);
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
    vec3 color = mix(vec3(0.08, 0.15, 0.35), vec3(0.3, 0.55, 1.0), daySide);
    float intensity = rim * mix(0.06, 0.22, daySide);
    gl_FragColor = vec4(color, intensity);
  }`;

export class Globe {
  constructor(container, { onHover, onSelect } = {}) {
    this.container = container;
    this.onHover = onHover || (() => {});
    this.onSelect = onSelect || (() => {});
    this.markers = new THREE.Group();
    this.labels = new THREE.Group();
    this.selectedId = null;
    this.labelsVisible = true;
    this._flyAnim = null;
    this._selRing = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x080c14);

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
      color: 0x8899bb, size: 0.05, sizeAttenuation: true, transparent: true, opacity: 0.7,
    })));

    this._buildLabels(countries);
    this.scene.add(this.labels);
    this.scene.add(this.markers);
    this._clock = new THREE.Clock();
    this.renderer.setAnimationLoop(() => this._tick());
  }

  _buildLabels(countries) {
    const dist = this.camera.position.length();
    const zoom = dist / 1.0;

    for (const f of countries.features) {
      const name = f.properties?.name;
      if (!name || !MAJOR_COUNTRIES.has(name)) continue;
      const [lat, lon] = featureCentroid(f);
      const sprite = makeLabelSprite(name.toUpperCase(), 52, '#ffffff', 'rgba(6, 12, 28, 0.72)');
      sprite.position.copy(latLonToVec3(lat, lon, 1.045));
      sprite.userData = { type: 'country', baseH: 0.085 };
      this.labels.add(sprite);
    }

    if (zoom < 2.2) {
      for (const [name, lat, lon] of NEWS_CITIES) {
        const sprite = makeLabelSprite(name, 40, '#8aa0b8', null);
        sprite.position.copy(latLonToVec3(lat, lon, 1.03));
        sprite.userData = { type: 'city', baseH: 0.055 };
        this.labels.add(sprite);
      }
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
      const lz = Math.max(0.3, Math.min(2.5, this.camera.position.length() / 1.6));
      for (const s of this.labels.children) {
        const bh = s.userData.baseH || 0.07;
        const aspect = s.material.map.image.width / s.material.map.image.height;
        s.scale.set(bh * aspect * lz, bh * lz, 1);
        const normal = s.position.clone().normalize();
        s.material.opacity = Math.max(0, normal.dot(this.camera.position.clone().normalize()) * 0.5 + 0.5);
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