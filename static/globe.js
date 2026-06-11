/* Vector globe renderer: procedural cartographic texture + 3D borders + event markers.
   No photo textures, no bloom — flat ops-console cartography. */
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const PALETTE = {
  ocean: '#0e1111',
  land: '#262d2f',
  coast: '#39414465',
  graticule: 'rgba(78, 86, 90, 0.16)',
  border3d: 0x4a5256,
};

export function sevColor(s) {
  if (s >= 0.7) return '#ff4632';
  if (s >= 0.45) return '#ffa01e';
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
  const decl = -23.44 * Math.cos(2 * Math.PI * (doy + 10) / 365.25);
  const utcHours = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const lon = -15 * (utcHours - 12);
  return latLonToVec3(decl, lon, 1).normalize();
}

function buildTexture(countriesGeo) {
  const W = 4096, H = 2048;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');

  ctx.fillStyle = PALETTE.ocean;
  ctx.fillRect(0, 0, W, H);

  // graticule every 15 degrees
  ctx.strokeStyle = PALETTE.graticule;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let lon = -180; lon <= 180; lon += 15) {
    const x = (lon + 180) / 360 * W;
    ctx.moveTo(x, 0); ctx.lineTo(x, H);
  }
  for (let lat = -75; lat <= 75; lat += 15) {
    const y = (90 - lat) / 180 * H;
    ctx.moveTo(0, y); ctx.lineTo(W, y);
  }
  ctx.stroke();

  const px = (lon, lat) => [(lon + 180) / 360 * W, (90 - lat) / 180 * H];
  ctx.fillStyle = PALETTE.land;
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
      ctx.fill('evenodd');
      ctx.stroke();
    }
  }

  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

function buildBorders(bordersMesh) {
  // topojson.mesh() gives a MultiLineString of all shared boundaries
  const positions = [];
  for (const line of bordersMesh.coordinates) {
    for (let i = 0; i < line.length - 1; i++) {
      const a = latLonToVec3(line[i][1], line[i][0], 1.0015);
      const b = latLonToVec3(line[i + 1][1], line[i + 1][0], 1.0015);
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.LineSegments(
    geo,
    new THREE.LineBasicMaterial({ color: PALETTE.border3d, transparent: true, opacity: 0.42 })
  );
}

const GLOBE_VERT = `
  varying vec2 vUv;
  varying vec3 vNormal;
  void main() {
    vUv = uv;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const GLOBE_FRAG = `
  uniform sampler2D map;
  uniform vec3 sunDir;
  varying vec2 vUv;
  varying vec3 vNormal;
  void main() {
    vec3 c = texture2D(map, vUv).rgb;
    float d = dot(normalize(vNormal), sunDir);
    float light = mix(0.75, 1.0, smoothstep(-0.12, 0.18, d));
    gl_FragColor = vec4(c * light, 1.0);
  }`;

const RIM_VERT = `
  varying vec3 vNormal;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const RIM_FRAG = `
  varying vec3 vNormal;
  void main() {
    float i = pow(0.62 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 5.0);
    gl_FragColor = vec4(vec3(0.55, 0.58, 0.60), 1.0) * i * 0.55;
  }`;

export class Globe {
  constructor(container, { onHover, onSelect } = {}) {
    this.container = container;
    this.onHover = onHover || (() => {});
    this.onSelect = onSelect || (() => {});
    this.markers = new THREE.Group();
    this.pulses = [];
    this.selectedId = null;
    this._flyAnim = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0c0d);

    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
    this.camera.position.copy(latLonToVec3(24, 15, 3.1));

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.rotateSpeed = 0.45;
    this.controls.minDistance = 1.25;
    this.controls.maxDistance = 6;
    this.controls.enablePan = false;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.12;
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
    const globeMat = new THREE.ShaderMaterial({
      uniforms: { map: { value: buildTexture(countries) }, sunDir: this.sunUniform },
      vertexShader: GLOBE_VERT,
      fragmentShader: GLOBE_FRAG,
    });
    this.scene.add(new THREE.Mesh(new THREE.SphereGeometry(1, 128, 96), globeMat));
    this.scene.add(buildBorders(borders));

    const rim = new THREE.Mesh(
      new THREE.SphereGeometry(1.035, 96, 72),
      new THREE.ShaderMaterial({
        vertexShader: RIM_VERT, fragmentShader: RIM_FRAG,
        side: THREE.BackSide, blending: THREE.AdditiveBlending, transparent: true,
      })
    );
    this.scene.add(rim);

    // sparse dim starfield for depth
    const starPos = [];
    for (let i = 0; i < 650; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(45);
      starPos.push(v.x, v.y, v.z);
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute('position', new THREE.Float32BufferAttribute(starPos, 3));
    this.scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({
      color: 0x6a6f72, size: 0.045, sizeAttenuation: true, transparent: true, opacity: 0.35,
    })));

    this.scene.add(this.markers);
    this._clock = new THREE.Clock();
    this.renderer.setAnimationLoop(() => this._tick());
  }

  setEvents(events) {
    for (const child of [...this.markers.children]) {
      child.geometry.dispose();
      child.material.dispose();
      this.markers.remove(child);
    }
    this.pulses = [];
    const now = Date.now();
    const recent = [];
    for (const ev of events) {
      const r = 0.0045 + ev.severity * 0.011;
      const mesh = new THREE.Mesh(
        new THREE.CircleGeometry(r, 20),
        new THREE.MeshBasicMaterial({
          color: sevColor(ev.severity), transparent: true, opacity: 0.88,
          depthWrite: false,
        })
      );
      const pos = latLonToVec3(ev.lat, ev.lon, 1.004);
      mesh.position.copy(pos);
      mesh.lookAt(pos.clone().multiplyScalar(2));
      mesh.userData.event = ev;
      mesh.renderOrder = 2;
      this.markers.add(mesh);
      const ageH = (now - Date.parse(ev.ts)) / 3.6e6;
      if (ageH < 3 && ev.severity >= 0.45) recent.push({ pos, r, sev: ev.severity });
    }
    // pulse rings on fresh significant events (cap for perf)
    for (const { pos, r, sev } of recent.slice(0, 60)) {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(1, 1.12, 28),
        new THREE.MeshBasicMaterial({
          color: sevColor(sev), transparent: true, opacity: 0.5,
          side: THREE.DoubleSide, depthWrite: false,
        })
      );
      ring.position.copy(pos.clone().setLength(1.006));
      ring.lookAt(ring.position.clone().multiplyScalar(2));
      ring.scale.setScalar(r);
      ring.renderOrder = 1;
      ring.userData.base = r;
      ring.userData.phase = Math.random() * 2.4;
      this.markers.add(ring);
      this.pulses.push(ring);
    }
    this.setSelected(this.selectedId);
  }

  setSelected(id) {
    this.selectedId = id;
    for (const m of this.markers.children) {
      const ev = m.userData.event;
      if (!ev) continue;
      const sel = ev.id === id;
      m.material.color.set(sel ? '#ffffff' : sevColor(ev.severity));
      m.material.opacity = sel ? 1 : 0.88;
    }
  }

  flyTo(lat, lon) {
    this.controls.autoRotate = false;
    const dist = Math.min(this.camera.position.length(), 2.4);
    const from = this.camera.position.clone().normalize();
    const to = latLonToVec3(lat, lon, 1).normalize();
    const qFrom = new THREE.Quaternion();
    const qTo = new THREE.Quaternion().setFromUnitVectors(from, to);
    this._flyAnim = { qFrom, qTo, from, dist, t0: performance.now(), dur: 750 };
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
    this.sunUniform && (this.sunUniform.value = subsolarDirection(new Date()));
    // markers keep a roughly constant screen size as the camera zooms
    const zoomScale = Math.min(Math.max((this.camera.position.length() - 1) / 2.1, 0.12), 1);
    for (const m of this.markers.children) {
      if (m.userData.event) m.scale.setScalar(zoomScale);
    }
    const t = this._clock.getElapsedTime();
    for (const ring of this.pulses) {
      const s = ((t + ring.userData.phase) % 2.4) / 2.4;
      ring.scale.setScalar(ring.userData.base * zoomScale * (1 + s * 3.2));
      ring.material.opacity = (1 - s) * 0.5;
    }
    this.renderer.render(this.scene, this.camera);
  }

  _pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.markers.children, false);
    for (const h of hits) {
      if (h.object.userData.event) return h.object.userData.event;
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
