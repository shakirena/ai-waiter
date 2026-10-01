// Генератор иконок PWA (public/icons/icon-192.png и icon-512.png).
// Без внешних зависимостей: PNG кодируется вручную через node:zlib.
// Запуск: `npm run icons` из каталога frontend. Результат коммитится в репозиторий.
//
// Рисунок: заливка цветом theme_color (#111827) на весь квадрат — фон для maskable,
// по центру белый клош (купол, ручка и подставка). Знак целиком внутри круга
// радиусом 40% от размера иконки — безопасная зона maskable-иконок.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const BACKGROUND = [0x11, 0x18, 0x27];
const FOREGROUND = [0xff, 0xff, 0xff];
const SUPERSAMPLE = 4;

const outDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");

// Принадлежность точки знаку в нормированных координатах (0..1, центр 0.5;0.5).
function isGlyph(x, y) {
  const cx = 0.5;
  // Купол: верхняя половина эллипса.
  const domeBaseY = 0.6;
  const rx = 0.27;
  const ry = 0.24;
  const dx = (x - cx) / rx;
  const dy = (y - domeBaseY) / ry;
  if (y <= domeBaseY && dx * dx + dy * dy <= 1) return true;
  // Ручка сверху купола.
  const knobY = domeBaseY - ry - 0.035;
  const kr = 0.045;
  if ((x - cx) ** 2 + (y - knobY) ** 2 <= kr * kr) return true;
  // Подставка (поднос) под куполом со скруглёнными краями.
  const trayTop = domeBaseY + 0.035;
  const trayBottom = trayTop + 0.05;
  const trayHalf = 0.32;
  const r = (trayBottom - trayTop) / 2;
  if (y >= trayTop && y <= trayBottom) {
    const ax = Math.abs(x - cx);
    if (ax <= trayHalf - r) return true;
    const ex = ax - (trayHalf - r);
    const ey = y - (trayTop + r);
    if (ex * ex + ey * ey <= r * r) return true;
  }
  return false;
}

function renderRgba(size) {
  const data = Buffer.alloc(size * size * 4);
  const samples = SUPERSAMPLE * SUPERSAMPLE;
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      let hits = 0;
      for (let sy = 0; sy < SUPERSAMPLE; sy++) {
        for (let sx = 0; sx < SUPERSAMPLE; sx++) {
          const x = (px + (sx + 0.5) / SUPERSAMPLE) / size;
          const y = (py + (sy + 0.5) / SUPERSAMPLE) / size;
          if (isGlyph(x, y)) hits++;
        }
      }
      const a = hits / samples;
      const i = (py * size + px) * 4;
      for (let c = 0; c < 3; c++) {
        data[i + c] = Math.round(BACKGROUND[c] * (1 - a) + FOREGROUND[c] * a);
      }
      data[i + 3] = 0xff;
    }
  }
  return data;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, payload) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(payload.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), payload]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function encodePng(size, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // глубина цвета
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  // Каждая строка начинается с байта фильтра 0 (None).
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    rgba.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

mkdirSync(outDir, { recursive: true });
for (const size of [192, 512]) {
  const file = join(outDir, `icon-${size}.png`);
  writeFileSync(file, encodePng(size, renderRgba(size)));
  console.log(`Создан ${file}`);
}
