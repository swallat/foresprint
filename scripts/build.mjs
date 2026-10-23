#!/usr/bin/env node
// Build and test helper for the Go core and the Wails window. One implementation for Windows,
// Linux and macOS, so the same `mise run <task>` works everywhere. It does what the release
// workflow does (.github/workflows/release-app.yml): same tags, same ldflags.
//
//   node scripts/build.mjs frontend   install (npm ci) and build the Svelte frontend into dist/
//   node scripts/build.mjs app        frontend + program with the window (tags desktop,production)
//   node scripts/build.mjs cli        program without the window (no cgo, no Node, no web view)
//   node scripts/build.mjs test       go vet + go test (no cgo, no Node)
//   node scripts/build.mjs check      frontend type check, translations and tests
//   node scripts/build.mjs all        test + check + app
//
// Options: --version X.Y.Z (default: $FORESPRINT_VERSION or dev), --out DIR (default: dist), --skip-npm-ci
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const goDir = join(root, "go");
const frontendDir = join(goDir, "internal", "desktop", "frontend");
const winresDir = join(goDir, "cmd", "foresprint", "winres");
const goWinres = "github.com/tc-hib/go-winres@v0.3.3";
const win = process.platform === "win32";

const args = process.argv.slice(2);
const command = args.shift();
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const version = opt("version", process.env.FORESPRINT_VERSION || "dev").replace(/^v/, "");
const outDir = resolve(root, opt("out", "dist"));
const exe = win ? "foresprint.exe" : "foresprint";

function run(cmd, cmdArgs, { cwd = root, env = {} } = {}) {
  console.log(`\n> ${cmd} ${cmdArgs.join(" ")}   (${cwd.replace(root, ".") || "."})`);
  const r = spawnSync(cmd, cmdArgs, {
    cwd,
    stdio: "inherit",
    shell: win && cmd === "npm", // npm is npm.cmd on Windows
    env: { ...process.env, ...env },
  });
  if (r.status !== 0) {
    if (r.error) console.error(r.error.message);
    console.error(`\nfailed: ${cmd} ${cmdArgs.join(" ")}`);
    process.exit(r.status ?? 1);
  }
}

const npm = (...a) => run("npm", a, { cwd: frontendDir });

function frontend() {
  if (!args.includes("--skip-npm-ci")) npm("ci");
  npm("run", "build");
}

function build(desktop) {
  mkdirSync(outDir, { recursive: true });
  const env = {};
  let tags = "";
  if (desktop) {
    tags = "desktop,production";
    if (process.platform === "linux") tags += ",webkit2_41"; // libwebkit2gtk-4.1-dev
    if (process.platform === "darwin") env.CGO_LDFLAGS = "-framework UniformTypeIdentifiers";
    env.CGO_ENABLED = "1";
  } else {
    env.CGO_ENABLED = "0"; // like the CLI archives of the release
  }
  // Program icon in the exe (Windows): once winres/winres.json exists (#383), go-winres writes a
  // .syso that go build links automatically. Not part of the release workflow yet.
  if (win && existsSync(join(winresDir, "winres.json"))) {
    run("go", ["run", goWinres, "make", "--arch", "amd64"], { cwd: join(goDir, "cmd", "foresprint") });
  }
  const goArgs = ["build", "-trimpath", "-ldflags", `-s -w -X main.version=${version}`];
  if (tags) goArgs.push("-tags", tags);
  goArgs.push("-o", join(outDir, exe), "./cmd/foresprint");
  run("go", goArgs, { cwd: goDir, env });
  console.log(`\nbuilt ${join(outDir, exe)}`);
}

const commands = {
  frontend,
  app() {
    frontend();
    build(true);
  },
  cli: () => build(false),
  test() {
    run("go", ["vet", "./..."], { cwd: goDir });
    run("go", ["test", "./..."], { cwd: goDir });
  },
  check() {
    if (!args.includes("--skip-npm-ci")) npm("ci");
    npm("run", "check");
    npm("test");
  },
  all() {
    this.test();
    this.check();
    args.push("--skip-npm-ci");
    this.app();
  },
};

if (!commands[command]) {
  console.error(`usage: node scripts/build.mjs <${Object.keys(commands).join("|")}> [--version X] [--out DIR]`);
  process.exit(2);
}
commands[command]();
