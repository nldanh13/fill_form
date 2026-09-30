import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

const root = process.cwd();
const localApp = join(root, "local_app");
const isWindows = process.platform === "win32";
const venvPython = join(localApp, ".venv", isWindows ? "Scripts/python.exe" : "bin/python");

function findPython() {
  if (existsSync(venvPython)) return { command: venvPython, args: [] };
  const candidates = isWindows
    ? [{ command: "py", args: ["-3"] }, { command: "python", args: [] }]
    : [{ command: "python3", args: [] }, { command: "python", args: [] }];
  for (const item of candidates) {
    const check = spawnSync(item.command, [...item.args, "--version"], { stdio: "ignore" });
    if (check.status === 0) return item;
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error("\n[LOI] Chua tim thay Python 3. Hay cai Python, sau do chay lai npm start.\n");
  process.exit(1);
}

const checkPlaywright = spawnSync(python.command, [...python.args, "-c", "import playwright"], { stdio: "ignore" });
if (checkPlaywright.status !== 0) {
  console.log("\n[THIET LAP] Lan dau su dung: dang cai Playwright va Chromium...");
  const setup = spawnSync(process.execPath, [join(root, "scripts", "setup-python.mjs")], { stdio: "inherit" });
  if (setup.status !== 0) process.exit(setup.status ?? 1);
}

console.log("\n[1/2] Khoi dong dich vu du lieu va Playwright...");
const backend = spawn(python.command, [...python.args, "server.py"], { cwd: localApp, stdio: "inherit" });
console.log("[2/2] Khoi dong giao dien tai http://127.0.0.1:3000 ...\n");
// Node 22 trên Windows có thể báo spawn EINVAL khi gọi thẳng file npm.cmd.
// Chạy qua cmd.exe là cách tương thích ổn định với PowerShell, CMD và đường dẫn có khoảng trắng.
const windowsShell = process.env.ComSpec || "C:\\Windows\\System32\\cmd.exe";
const frontendEnv = { ...process.env, WRANGLER_LOG_PATH: ".wrangler/wrangler.log" };
const frontend = isWindows
  ? spawn(windowsShell, ["/d", "/s", "/c", "npm run start:ui"], { cwd: root, stdio: "inherit", windowsHide: false, env: frontendEnv })
  : spawn("npm", ["run", "start:ui"], { cwd: root, stdio: "inherit", env: frontendEnv });

const opener = isWindows
  ? ["explorer.exe", ["http://127.0.0.1:3000"]]
  : process.platform === "darwin"
    ? ["open", ["http://127.0.0.1:3000"]]
    : ["xdg-open", ["http://127.0.0.1:3000"]];
setTimeout(() => {
  try {
    const browser = spawn(opener[0], opener[1], { stdio: "ignore", detached: true });
    browser.on("error", () => {
      console.log("[INFO] Hay mo thu cong: http://127.0.0.1:3000");
    });
    browser.unref();
  } catch {
    console.log("[INFO] Hay mo thu cong: http://127.0.0.1:3000");
  }
}, 3500);

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  backend.kill(); frontend.kill();
  setTimeout(() => process.exit(code), 200);
}
backend.on("exit", code => { if (!stopping) stop(code ?? 1); });
frontend.on("exit", code => { if (!stopping) stop(code ?? 1); });
backend.on("error", error => { console.error("[LOI BACKEND]", error.message); stop(1); });
frontend.on("error", error => { console.error("[LOI GIAO DIEN]", error.message); stop(1); });
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
