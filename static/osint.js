/** Client-side JPEG EXIF GPS extraction for OSINT geolocation. */

function readU16(buf, off, le) {
  return le ? buf[off] | (buf[off + 1] << 8) : (buf[off] << 8) | buf[off + 1];
}

function readU32(buf, off, le) {
  return le
    ? buf[off] | (buf[off + 1] << 8) | (buf[off + 2] << 16) | (buf[off + 3] << 24)
    : (buf[off] << 24) | (buf[off + 1] << 16) | (buf[off + 2] << 8) | buf[off + 3];
}

function parseRational(buf, off, le) {
  const num = readU32(buf, off, le);
  const den = readU32(buf, off + 4, le);
  return den ? num / den : 0;
}

function dmsToDec(dms, ref) {
  const deg = dms[0] + dms[1] / 60 + dms[2] / 3600;
  return ref === 'S' || ref === 'W' ? -deg : deg;
}

export async function extractGpsFromImage(file) {
  const buf = new Uint8Array(await file.arrayBuffer());
  if (buf[0] !== 0xff || buf[1] !== 0xd8) return null;

  let off = 2;
  while (off < buf.length - 4) {
    if (buf[off] !== 0xff) break;
    const marker = buf[off + 1];
    const len = readU16(buf, off + 2, false);
    if (marker === 0xe1) {
      const start = off + 4;
      const header = String.fromCharCode(...buf.slice(start, start + 4));
      if (header === 'Exif') {
        const tiff = start + 6;
        const le = buf[tiff] === 0x49;
        const ifd0 = tiff + readU32(buf, tiff + 4, le);
        const gps = findGpsIfd(buf, ifd0, tiff, le);
        if (gps) return gps;
      }
    }
    off += 2 + len;
  }
  return null;
}

function findGpsIfd(buf, ifdOff, tiff, le) {
  const n = readU16(buf, ifdOff, le);
  let gpsPtr = 0;
  for (let i = 0; i < n; i++) {
    const e = ifdOff + 2 + i * 12;
    const tag = readU16(buf, e, le);
    if (tag === 0x8825) gpsPtr = readU32(buf, e + 8, le);
  }
  if (!gpsPtr) return null;
  const gpsIfd = tiff + gpsPtr;
  const gn = readU16(buf, gpsIfd, le);
  let lat = null;
  let lon = null;
  let latRef = 'N';
  let lonRef = 'E';
  for (let i = 0; i < gn; i++) {
    const e = gpsIfd + 2 + i * 12;
    const tag = readU16(buf, e, le);
    const typ = readU16(buf, e + 2, le);
    const cnt = readU32(buf, e + 4, le);
    let valOff = e + 8;
    if (typ === 5 && cnt === 3) {
      const ptr = readU32(buf, e + 8, le) + tiff;
      const dms = [
        parseRational(buf, ptr, le),
        parseRational(buf, ptr + 8, le),
        parseRational(buf, ptr + 16, le),
      ];
      if (tag === 2) lat = dms;
      if (tag === 4) lon = dms;
    } else if (typ === 2 && cnt === 2) {
      const chars = buf.slice(valOff, valOff + 2);
      const ref = String.fromCharCode(chars[0]);
      if (tag === 1) latRef = ref;
      if (tag === 3) lonRef = ref;
    }
  }
  if (!lat || !lon) return null;
  return {
    lat: dmsToDec(lat, latRef),
    lon: dmsToDec(lon, lonRef),
    source: 'exif',
  };
}