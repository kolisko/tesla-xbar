#!/usr/bin/env node
// Development only: rasterize the editable SVGs into macOS template images.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');
const root = path.resolve(__dirname, '..');
const directory = path.join(root, 'src/icons');
const names = ['charging', 'camp', 'pet', 'fan', 'unlocked', 'sentry', 'frunk', 'trunk'];
const drawings = Object.fromEntries(names.map(name => [name,
  fs.readFileSync(path.join(directory, `${name}.svg`), 'utf8')
    .replace(/^<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '')]));

function svg(width, height, content) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${content}</svg>`;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function retinaDensity(png) {
  // 32 physical pixels occupy 16 points in NSImage. Keep only PNG image chunks;
  // no EXIF, personal metadata, or dependency on host image-resizing behavior.
  const chunks = [png.subarray(0, 8)];
  for (let offset = 8; offset < png.length;) {
    const size = png.readUInt32BE(offset);
    const type = png.toString('ascii', offset + 4, offset + 8);
    if (['IHDR', 'PLTE', 'tRNS', 'IDAT', 'IEND'].includes(type)) {
      chunks.push(png.subarray(offset, offset + size + 12));
    }
    if (type === 'IHDR') {
      const chunk = Buffer.alloc(21);
      chunk.writeUInt32BE(9, 0);
      chunk.write('pHYs', 4, 'ascii');
      chunk.writeUInt32BE(5669, 8);
      chunk.writeUInt32BE(5669, 12);
      chunk[16] = 1;
      chunk.writeUInt32BE(crc32(chunk.subarray(4, 17)), 17);
      chunks.push(chunk);
    }
    offset += size + 12;
  }
  return Buffer.concat(chunks);
}

async function main() {
  for (const charging of [false, true]) {
    for (const mode of [null, 'camp', 'pet']) {
      const optional = ['fan', 'unlocked', 'sentry', 'frunk', 'trunk'];
      for (let mask = 0; mask < 2 ** optional.length; mask++) {
          const icons = [charging && 'charging', mode,
            ...optional.filter((_, index) => mask & (1 << index))].filter(Boolean);
          if (!icons.length) continue;
          const strip = svg(icons.length * 19 - 3, 16, icons.map((name, index) =>
            `<g transform="translate(${index * 19} 0)">${drawings[name]}</g>`).join(''));
          const png = await sharp(Buffer.from(strip), {density: 144}).png().toBuffer();
          fs.writeFileSync(path.join(directory, icons.join('-') + '.png'), retinaDensity(png));
      }
    }
  }
  // Fictional documentation preview, never a capture of a user's vehicle.
  const preview = svg(940, 380, `<rect width="940" height="380" rx="20" fill="#202932"/>
    <g font-family="Arial, sans-serif" fill="#e6edf3">
    <text x="28" y="36" font-size="19" font-weight="bold">Live vehicle indicators</text>
    ${names.map((name, i) => `<g transform="translate(${34 + (i % 4) * 230} ${65 + Math.floor(i / 4) * 110}) scale(2)" fill="#e6edf3">${drawings[name].replaceAll('#000', '#e6edf3')}</g>
      <text x="${28 + (i % 4) * 230}" y="${126 + Math.floor(i / 4) * 110}" font-size="17">${['Charging', 'Camp Mode', 'Pet Mode', 'Climate on', 'Unlocked', 'Sentry', 'Front trunk open', 'Rear trunk open'][i]}</text>`).join('')}
    <rect x="28" y="268" width="360" height="52" rx="12" fill="#12191f"/>
    ${['charging', 'unlocked', 'frunk', 'trunk'].map((name, i) => `<g transform="translate(${46 + i * 28} 285)" fill="#e6edf3">${drawings[name].replaceAll('#000', '#e6edf3')}</g>`).join('')}
    <text x="168" y="303" fill="#32cd66" font-size="24">360 km</text>
    <text x="28" y="357" font-size="14" fill="#a0a6ad">Illustrative data. Active indicators require a fresh, online reading.</text></g>`);
  fs.writeFileSync(path.join(root, 'docs/images/status-icons.svg'), preview + '\n');
  await sharp(Buffer.from(preview)).png().toFile(path.join(root, 'docs/images/status-icons.png'));
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
