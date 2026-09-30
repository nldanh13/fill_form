// Dong goi du an thanh mot file zip "sach" de gui di.
// Tu dong loai bo: node_modules, cache build, .venv, ho so trinh duyet,
// database/log runtime, __pycache__... vi tat ca se duoc tu tao lai khi
// nguoi nhan chay `npm install && npm start`.
//
// Khong dung goi ngoai nao (khong can `npm install` truoc khi chay lan dau) -
// tu tao file .zip bang dinh dang ZIP chuan (deflate) qua module zlib co san.
import { createWriteStream, existsSync, mkdirSync, statSync, readFileSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { deflateRawSync } from "node:zlib";
import { join, relative, sep } from "node:path";
import process from "node:process";

const root = process.cwd();
const outDir = join(root, "dist-clean");
const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
const outFile = join(outDir, `tro-ly-dien-phieu-clean-${stamp}.zip`);

// Thu muc/ten bi loai hoan toan (du nam o bat ky cap nao trong cay thu muc)
const IGNORED_DIR_NAMES = new Set([
  "node_modules",
  ".git",
  ".wrangler",
  ".next",
  "dist",
  "dist-clean",
  ".sites-runtime",
  ".venv",
  "__pycache__",
  "browser_profile",
  ".pw_profile",
  "playwright_profile",
]);

// Duong dan tuong doi cu the bi loai (so voi root du an)
const IGNORED_RELATIVE_PATHS = new Set([
  join("local_app", "data"), // db/log/backup/archive runtime, tu tao lai khi chay
]);

const IGNORED_FILE_SUFFIXES = [".pyc", ".log", ".db", ".db-journal", ".db-wal", ".db-shm"];
const IGNORED_FILE_NAMES = new Set([".DS_Store", "Thumbs.db"]);

function isIgnored(relPath, isDir) {
  const parts = relPath.split(sep);
  const name = parts[parts.length - 1];
  if (isDir && IGNORED_DIR_NAMES.has(name)) return true;
  for (const ignoredRel of IGNORED_RELATIVE_PATHS) {
    if (relPath === ignoredRel || relPath.startsWith(ignoredRel + sep)) return true;
  }
  if (!isDir) {
    if (IGNORED_FILE_NAMES.has(name)) return true;
    if (IGNORED_FILE_SUFFIXES.some((suf) => name.endsWith(suf))) return true;
  }
  return false;
}

async function collectFiles(dir, acc) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const abs = join(dir, entry.name);
    const rel = relative(root, abs);
    const isDir = entry.isDirectory();
    if (isIgnored(rel, isDir)) continue;
    if (isDir) {
      await collectFiles(abs, acc);
    } else if (entry.isFile()) {
      acc.push({ abs, rel });
    }
  }
  return acc;
}

// ---- CRC32 (chuan zip) ----
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
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    crc = CRC_TABLE[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date) {
  const time =
    ((date.getHours() & 0x1f) << 11) | ((date.getMinutes() & 0x3f) << 5) | ((date.getSeconds() >> 1) & 0x1f);
  const dosDate =
    (((date.getFullYear() - 1980) & 0x7f) << 9) | (((date.getMonth() + 1) & 0xf) << 5) | (date.getDate() & 0x1f);
  return { time, dosDate };
}

// ---- Tao file .zip theo dinh dang chuan (khong dung thu vien ngoai) ----
function buildZip(files) {
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;
  const { time, dosDate } = dosDateTime(new Date());

  for (const { rel, abs } of files) {
    const nameBuf = Buffer.from(rel.split(sep).join("/"), "utf8");
    const content = readFileSync(abs);
    const crc = crc32(content);
    const compressed = deflateRawSync(content, { level: 9 });
    const useDeflate = compressed.length < content.length;
    const data = useDeflate ? compressed : content;
    const method = useDeflate ? 8 : 0;

    const localHeader = Buffer.alloc(30);
    localHeader.writeUInt32LE(0x04034b50, 0);
    localHeader.writeUInt16LE(20, 4); // version needed
    localHeader.writeUInt16LE(0x0800, 6); // flag: UTF-8 filenames
    localHeader.writeUInt16LE(method, 8);
    localHeader.writeUInt16LE(time, 10);
    localHeader.writeUInt16LE(dosDate, 12);
    localHeader.writeUInt32LE(crc, 14);
    localHeader.writeUInt32LE(data.length, 18);
    localHeader.writeUInt32LE(content.length, 22);
    localHeader.writeUInt16LE(nameBuf.length, 26);
    localHeader.writeUInt16LE(0, 28);

    localChunks.push(localHeader, nameBuf, data);

    const centralHeader = Buffer.alloc(46);
    centralHeader.writeUInt32LE(0x02014b50, 0);
    centralHeader.writeUInt16LE(20, 4); // version made by
    centralHeader.writeUInt16LE(20, 6); // version needed
    centralHeader.writeUInt16LE(0x0800, 8);
    centralHeader.writeUInt16LE(method, 10);
    centralHeader.writeUInt16LE(time, 12);
    centralHeader.writeUInt16LE(dosDate, 14);
    centralHeader.writeUInt32LE(crc, 16);
    centralHeader.writeUInt32LE(data.length, 20);
    centralHeader.writeUInt32LE(content.length, 24);
    centralHeader.writeUInt16LE(nameBuf.length, 28);
    centralHeader.writeUInt16LE(0, 30); // extra len
    centralHeader.writeUInt16LE(0, 32); // comment len
    centralHeader.writeUInt16LE(0, 34); // disk number
    centralHeader.writeUInt16LE(0, 36); // internal attrs
    centralHeader.writeUInt32LE((0o100644 << 16) >>> 0, 38); // external attrs (unix perms)
    centralHeader.writeUInt32LE(offset, 42);

    centralChunks.push(centralHeader, nameBuf);

    offset += localHeader.length + nameBuf.length + data.length;
  }

  const centralDirStart = offset;
  const centralDirBuf = Buffer.concat(centralChunks);

  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralDirBuf.length, 12);
  end.writeUInt32LE(centralDirStart, 16);
  end.writeUInt16LE(0, 20);

  return Buffer.concat([...localChunks, centralDirBuf, end]);
}

async function main() {
  if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true });

  const files = await collectFiles(root, []);
  if (files.length === 0) {
    console.error("[LOI] Khong tim thay file nao de dong goi.");
    process.exit(1);
  }

  const zipBuffer = buildZip(files);
  await new Promise((resolve, reject) => {
    const out = createWriteStream(outFile);
    out.on("finish", resolve);
    out.on("error", reject);
    out.end(zipBuffer);
  });

  const sizeMb = (statSync(outFile).size / (1024 * 1024)).toFixed(2);
  console.log(`\n[XONG] Da dong goi ${files.length} file (${sizeMb} MB):\n${outFile}\n`);
}

main().catch((err) => {
  console.error("[LOI]", err.message);
  process.exit(1);
});
