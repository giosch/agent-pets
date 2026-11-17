// Run the installed hook commands from an unrelated cwd, exactly as the runtimes do.
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const { once } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { chromium } = require("playwright");

const python = process.env.HABITAT_PYTHON || "python";
const entry = path.resolve(__dirname, "../habitat.py");
const work = fs.mkdtempSync(path.join(os.tmpdir(), "clawd habitat "));
const state = path.join(work, "state");
const env = { ...process.env, CLAUDE_CONFIG_DIR: path.join(work, "claude"), CODEX_HOME: path.join(work, "codex") };
const options = { env, cwd: work, encoding: "utf8", windowsHide: true, timeout: 10000 };
let host;
let browser;

function check(result) {
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr);
}
function hook(source, session, event, data = {}) {
  const file = source === "claude" ? path.join(env.CLAUDE_CONFIG_DIR, "settings.json") : path.join(env.CODEX_HOME, "hooks.json");
  const handler = JSON.parse(fs.readFileSync(file)).hooks[event][0].hooks[0];
  const input = JSON.stringify({ session_id: session, hook_event_name: event, ...data });
  if (source === "claude") {
    check(spawnSync(handler.command, handler.args, { ...options, input }));
  } else {
    const cmd = process.platform === "win32" ? handler.commandWindows : handler.command;
    const result = spawnSync(cmd, { ...options, shell: true, input });
    check(result);
    assert.deepEqual(JSON.parse(result.stdout), {});
  }
}

async function startHost() {
  host = spawn(python, [entry, "--state-dir", state, "serve", "--port", "0"], {
    env, cwd: work, windowsHide: true, stdio: ["ignore", "pipe", "inherit"]
  });
  const lines = readline.createInterface({ input: host.stdout });
  const url = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Habitat startup timed out")), 30000);
    host.once("error", error => { clearTimeout(timeout); reject(error); });
    host.once("exit", code => { clearTimeout(timeout); reject(new Error("Host exited " + code)); });
    lines.once("line", line => { clearTimeout(timeout); resolve(line.match(/http:\/\/\S+/)[0]); });
  });
  return url;
}
async function stopHost() {
  if (host && host.exitCode === null && host.signalCode === null) {
    const exited = once(host, "exit");
    host.kill();
    await exited;
  }
}

async function main() {
  check(spawnSync(python, [entry, "--state-dir", state, "install-hooks"], options));
  let url = await startHost();
  browser = await chromium.launch({ headless: true, executablePath: process.env.HABITAT_CHROMIUM || undefined });
  const context = await browser.newContext({ viewport: { width: 1180, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  context.on("weberror", error => errors.push(error.error().message));
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.locator("#connection[data-state=live]").waitFor();
  const pet = (page, id) => page.locator('[data-session="' + id + '"]');
  for (const [source, sid, tool] of [
    ["claude", "a", "Edit"], ["codex", "b", "apply_patch"], ["claude", "c", "Read"], ["codex", "d", "Bash"]
  ]) {
    hook(source, sid, "SessionStart");
    hook(source, sid, "UserPromptSubmit");
    hook(source, sid, "PreToolUse", { tool_name: tool, tool_use_id: sid });
  }
  await page.locator("#overflow:not([hidden])").waitFor();
  assert.deepEqual(await page.locator(".pet").evaluateAll(nodes => nodes.map(n => n.dataset.session)),
                   ["claude:a", "codex:b", "claude:c"]);
  assert.equal(await pet(page, "codex:b").getAttribute("data-pose"), "editing");
  const color = await pet(page, "claude:a").getAttribute("data-palette");
  hook("codex", "d", "PermissionRequest", { tool_name: "Bash", tool_use_id: "d" });
  await pet(page, "codex:d").locator(".signal[data-kind=approval]").waitFor();
  assert.equal(await pet(page, "claude:c").count(), 0);
  hook("claude", "a", "Stop");
  await page.locator('[data-session="claude:a"][data-moment=completed]').waitFor();
  await pet(page, "claude:a").locator(".signal[data-kind=ready]").waitFor();
  const second = await context.newPage();
  await second.goto(url, { waitUntil: "domcontentloaded" });
  await pet(second, "claude:a").locator(".signal[data-kind=ready]").waitFor();
  assert.equal(await second.locator("[data-moment]").count(), 0);
  assert.equal(await pet(second, "claude:a").getAttribute("data-palette"), color);
  await page.selectOption("#habitat", "grove");
  await second.locator('#scene[aria-label="Pine Grove"]').waitFor();
  assert.equal(await pet(page, "claude:a").getAttribute("data-palette"), color);
  await page.selectOption("#character", "fox");
  await page.waitForFunction(() => [...document.querySelectorAll(".pet > img")].every(
    img => img.src.includes("/fox/") && img.complete && img.naturalWidth > 0
  ));
  assert.equal(new Set(await page.locator(".pet").evaluateAll(ns => ns.map(n => n.dataset.palette))).size, 3);
  if (process.env.HABITAT_SCREENSHOT) await page.screenshot({ path: process.env.HABITAT_SCREENSHOT });
  hook("claude", "a", "UserPromptSubmit");
  await pet(page, "claude:a").locator(".signal").waitFor({ state: "hidden" });
  hook("codex", "d", "PostToolUse", { tool_name: "Bash", tool_use_id: "d" });
  await pet(page, "codex:d").waitFor({ state: "detached" });
  await pet(page, "claude:c").waitFor();
  const before = await (await fetch(url + "v1/snapshot")).json();
  assert.deepEqual(before.sessions.map(s => s.attention), ["none", "none", "none", "none"]);
  await stopHost();
  url = await startHost();
  assert.deepEqual(await (await fetch(url + "v1/snapshot")).json(), before);
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await pet(page, "claude:a").waitFor();
  assert.equal(await pet(page, "claude:a").getAttribute("data-palette"), color);
  for (const [source, id] of [["claude","a"], ["codex","b"], ["claude","c"], ["codex","d"]]) {
    hook(source, id, "SessionEnd");
  }
  await page.locator("[data-resting]").waitFor();
  assert.deepEqual(errors, []);
  console.log("Four-session browser acceptance passed on " + process.platform);
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stopHost();
  fs.rmSync(work, { recursive: true, force: true });
});
