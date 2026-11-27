// Produce correctly sized install icons from the existing VODLoft logo.
// Uses only Node built-ins so it also works in the dependency-free Docker build.
import {readFileSync, writeFileSync} from 'node:fs'
import {deflateSync, inflateSync} from 'node:zlib'

const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])

function paeth(a, b, c) {
  const p = a + b - c
  const da = Math.abs(p - a)
  const db = Math.abs(p - b)
  const dc = Math.abs(p - c)
  return da <= db && da <= dc ? a : db <= dc ? b : c
}

function decodePng(buffer) {
  if (!buffer.subarray(0, 8).equals(signature)) throw new Error('Source logo is not a PNG')

  let width = 0
  let height = 0
  const idat = []
  for (let offset = 8; offset < buffer.length;) {
    const length = buffer.readUInt32BE(offset)
    const type = buffer.toString('ascii', offset + 4, offset + 8)
    const chunk = buffer.subarray(offset + 8, offset + 8 + length)
    if (type === 'IHDR') {
      width = chunk.readUInt32BE(0)
      height = chunk.readUInt32BE(4)
      if (chunk[8] !== 8 || chunk[9] !== 6 || chunk[12] !== 0) {
        throw new Error('Source logo must be an 8-bit, non-interlaced RGBA PNG')
      }
    } else if (type === 'IDAT') {
      idat.push(chunk)
    } else if (type === 'IEND') {
      break
    }
    offset += length + 12
  }
  if (!width || !height || !idat.length) throw new Error('Source logo PNG is incomplete')

  const raw = inflateSync(Buffer.concat(idat))
  const rowLength = width * 4
  if (raw.length !== height * (rowLength + 1)) throw new Error('Unexpected PNG scanline size')
  const pixels = Buffer.alloc(width * height * 4)

  for (let y = 0; y < height; y++) {
    const rowStart = y * (rowLength + 1)
    const filter = raw[rowStart]
    if (filter > 4) throw new Error('Unsupported PNG filter')
    const outputStart = y * rowLength
    for (let x = 0; x < rowLength; x++) {
      const left = x >= 4 ? pixels[outputStart + x - 4] : 0
      const above = y > 0 ? pixels[outputStart - rowLength + x] : 0
      const upperLeft = y > 0 && x >= 4 ? pixels[outputStart - rowLength + x - 4] : 0
      const predictor = [0, left, above, (left + above) >>> 1, paeth(left, above, upperLeft)][filter]
      pixels[outputStart + x] = (raw[rowStart + x + 1] + predictor) & 255
    }
  }
  return {width, height, pixels}
}

function resizePng({width, height, pixels}, size) {
  const output = Buffer.alloc(size * size * 4)
  for (let y = 0; y < size; y++) {
    const sourceY = Math.max(0, Math.min(height - 1, (y + 0.5) * height / size - 0.5))
    const y0 = Math.floor(sourceY)
    const y1 = Math.min(height - 1, y0 + 1)
    const fy = sourceY - y0
    for (let x = 0; x < size; x++) {
      const sourceX = Math.max(0, Math.min(width - 1, (x + 0.5) * width / size - 0.5))
      const x0 = Math.floor(sourceX)
      const x1 = Math.min(width - 1, x0 + 1)
      const fx = sourceX - x0
      const samples = [
        [(y0 * width + x0) * 4, (1 - fx) * (1 - fy)],
        [(y0 * width + x1) * 4, fx * (1 - fy)],
        [(y1 * width + x0) * 4, (1 - fx) * fy],
        [(y1 * width + x1) * 4, fx * fy],
      ]
      let alpha = 0
      const rgb = [0, 0, 0]
      for (const [index, weight] of samples) {
        const weightedAlpha = pixels[index + 3] * weight
        alpha += weightedAlpha
        for (let channel = 0; channel < 3; channel++) {
          rgb[channel] += pixels[index + channel] * weightedAlpha
        }
      }
      const dest = (y * size + x) * 4
      for (let channel = 0; channel < 3; channel++) {
        output[dest + channel] = alpha ? Math.round(rgb[channel] / alpha) : 0
      }
      output[dest + 3] = Math.round(alpha)
    }
  }
  return output
}

// The logo is a white house with nothing behind it, which disappears on a light browser tab bar or home screen.
// Every icon therefore puts it on VODLoft's dark navy (#0f172a, the manifest's theme colour).
const NAVY = [15, 23, 42]

// One icon: the logo at logoScale of the icon's width, centred on a navy square whose corners are rounded by
// radius (a fraction of the width; 0 fills the whole square).
function tileIcon(source, size, logoScale, radius) {
  const logoSize = Math.round(size * logoScale)
  const inset = Math.floor((size - logoSize) / 2)
  const logo = resizePng(source, logoSize)
  const corner = radius * size
  const pixels = Buffer.alloc(size * size * 4)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const index = (y * size + x) * 4
      pixels[index] = NAVY[0]
      pixels[index + 1] = NAVY[1]
      pixels[index + 2] = NAVY[2]
      pixels[index + 3] = Math.round(255 * cornerCoverage(x + 0.5, y + 0.5, size, corner))
    }
  }
  for (let y = 0; y < logoSize; y++) {
    for (let x = 0; x < logoSize; x++) {
      const from = (y * logoSize + x) * 4
      const to = ((y + inset) * size + (x + inset)) * 4
      const opacity = logo[from + 3] / 255
      for (let c = 0; c < 3; c++) {
        pixels[to + c] = Math.round(logo[from + c] * opacity + pixels[to + c] * (1 - opacity))
      }
    }
  }
  return pixels
}

// How much of the pixel centred on (x, y) lies inside a square of the given size with rounded corners.
function cornerCoverage(x, y, size, corner) {
  if (!corner) return 1
  const cx = Math.min(Math.max(x, corner), size - corner)
  const cy = Math.min(Math.max(y, corner), size - corner)
  const distance = Math.hypot(x - cx, y - cy)
  return Math.min(1, Math.max(0, corner - distance + 0.5))
}

const crcTable = Array.from({length: 256}, (_, n) => {
  let value = n
  for (let j = 0; j < 8; j++) {
    value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : value >>> 1
  }
  return value >>> 0
})

function pngChunk(type, bytes) {
  const typeBytes = Buffer.from(type, 'ascii')
  const content = Buffer.concat([typeBytes, bytes])
  let crc = 0xffffffff
  for (const byte of content) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8)
  const result = Buffer.alloc(content.length + 8)
  result.writeUInt32BE(bytes.length, 0)
  content.copy(result, 4)
  result.writeUInt32BE((crc ^ 0xffffffff) >>> 0, result.length - 4)
  return result
}

function encodePng(size, pixels) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8  // bit depth
  ihdr[9] = 6  // RGBA
  const rowLength = size * 4
  const raw = Buffer.alloc(size * (rowLength + 1))
  for (let y = 0; y < size; y++) {
    pixels.copy(raw, y * (rowLength + 1) + 1, y * rowLength, (y + 1) * rowLength)
  }
  return Buffer.concat([
    signature,
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', deflateSync(raw, {level: 9})),
    pngChunk('IEND', Buffer.alloc(0)),
  ])
}

// A Windows icon file that holds each size as a PNG, which every current browser reads.
function encodeIco(images) {
  const header = Buffer.alloc(6 + images.length * 16)
  header.writeUInt16LE(1, 2)  // type: icon
  header.writeUInt16LE(images.length, 4)
  let offset = header.length
  images.forEach(([size, png], index) => {
    const entry = 6 + index * 16
    header[entry] = size >= 256 ? 0 : size
    header[entry + 1] = size >= 256 ? 0 : size
    header.writeUInt16LE(1, entry + 4)  // colour planes
    header.writeUInt16LE(32, entry + 6)  // bits per pixel
    header.writeUInt32LE(png.length, entry + 8)
    header.writeUInt32LE(offset, entry + 12)
    offset += png.length
  })
  return Buffer.concat([header, ...images.map(([, png]) => png)])
}

const publicFile = (name) => new URL(`../public/${name}`, import.meta.url)
const source = decodePng(readFileSync(publicFile('logo-square-house.png')))
// Browser tabs: a rounded tile filled almost edge to edge by the house, so it still reads at 16 pixels.
writeFileSync(publicFile('favicon.ico'), encodeIco(
  [16, 32, 48, 64, 128, 256].map((size) => [size, encodePng(size, tileIcon(source, size, 0.92, 0.2))]),
))
// iOS rounds the home screen icon itself and turns transparency black, so it gets the full square.
writeFileSync(publicFile('pwa-icon-180.png'), encodePng(180, tileIcon(source, 180, 0.8, 0)))
// Installed app icons on other systems: the same rounded tile with more room around the house.
for (const size of [192, 512]) {
  writeFileSync(publicFile(`pwa-icon-${size}.png`), encodePng(size, tileIcon(source, size, 0.8, 0.2)))
}
// The whole logo fits inside the central 80%-diameter maskable safe circle.
writeFileSync(publicFile('pwa-maskable-512.png'), encodePng(512, tileIcon(source, 512, 288 / 512, 0)))
