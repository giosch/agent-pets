const el = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1)).get("manage");
if (fragment) {
  sessionStorage.setItem("habitat-management", fragment);
  history.replaceState(null, "", location.pathname);
}
const key = sessionStorage.getItem("habitat-management");
const names = {claude:"Claude Code", codex:"Codex"};
const rows = {};
let trust = "unknown";
let stopped = false;
let lastTrustCheck = 0;
async function action(action, fields = {}) {
  const res = await fetch("/manage", {method:"POST", headers:{"Content-Type":"application/json",
    Authorization:"Bearer " + key}, body:JSON.stringify({action,...fields})});
  if (res.status === 403) throw Error("Open Clawd Tank from your applications to manage this host.");
  const result = await res.json();
  if (!res.ok) throw Error(result.error || "The action could not finish.");
  return result;
}
function button(label, fn) {
  const b = document.createElement("button");
  b.textContent = label;
  b.disabled = !key;
  b.onclick = async () => {
    b.disabled = true;
    try { await fn(); await refresh(); }
    catch (err) { el("feedback").textContent = err.message; }
    finally { b.disabled = !key; }
  };
  return b;
}
for (const [source, name] of Object.entries(names)) {
  const row = document.createElement("article");
  const title = document.createElement("h2");
  title.textContent = name;
  const state = document.createElement("p"), path = document.createElement("code");
  const actions = document.createElement("div");
  actions.className = "actions";
  const install = button("Connect", async () => {
    const r = await action("install",{source});
    el("feedback").textContent = r.verified ? name + " hook command verified." : name + " hook command needs attention.";
    lastTrustCheck = 0;
  });
  const check = button("Check command", async () => {
    const r = await action("probe",{source});
    el("feedback").textContent = r.verified ? name + " command reached the host." : "Repair this integration and retry.";
    lastTrustCheck = 0;
  });
  const remove = button("Disconnect", async () => { await action("remove",{source}); el("feedback").textContent = name + " disconnected."; });
  actions.append(install,check,remove);
  row.append(title,state,path,actions);
  el("agents").append(row);
  rows[source] = {state,path,install,check,remove};
}
async function refresh() {
  if (stopped) return;
  const res = await fetch("/v1/connections", {cache:"no-store"});
  if (!res.ok) throw Error("Connections are unavailable.");
  const data = await res.json();
  el("status").textContent = "Host running · " + data.displays + (data.displays === 1 ? " habitat display" : " habitat displays");
  el("login").checked = data.login;
  if (key && data.agents.codex.state === "installed" && Date.now() - lastTrustCheck > 30000) {
    lastTrustCheck = Date.now();
    trust = (await action("trust")).trust;
  }
  for (const [source,a] of Object.entries(data.agents)) {
    const row = rows[source], installed = a.state === "installed";
    row.path.textContent = a.profile;
    row.install.textContent = a.state === "available" ? "Connect" : "Repair";
    row.check.hidden = !installed;
    row.remove.hidden = a.state === "available";
    if (a.state === "available") row.state.textContent = "Available to connect";
    else if (a.state === "invalid") row.state.textContent = "Settings file needs attention. Correct its JSON before connecting.";
    else if (!installed) row.state.textContent = "Hook needs repair";
    else if (source === "codex" && trust === "review") row.state.textContent = "Review the habitat hooks in Codex Settings → Hooks or /hooks.";
    else if (!a.last) row.state.textContent = "Waiting for first event. Send a prompt in a new local session.";
    else row.state.textContent = "Last activity · " + new Date(a.last.time * 1000).toLocaleString() + " · " + a.last.kind;
  }
}
el("login").disabled = !key;
el("stop").disabled = !key;
el("hint").hidden = !!key;
el("login").onchange = async () => {
  try { await action("login",{enabled:el("login").checked}); }
  catch(e) { el("feedback").textContent = e.message; await refresh(); }
};
el("finish").onclick = async () => { if (key) await action("finish"); location.assign("/"); };
el("stop").onclick = async () => {
  try { await action("stop"); stopped = true; el("status").textContent = "Host stopped. Open Clawd Tank to start it again."; }
  catch(e) { el("feedback").textContent = e.message; }
};
async function poll() {
  try { await refresh(); } catch(e) { el("feedback").textContent = e.message; }
  if (!stopped) setTimeout(poll, 3000);
}
poll();
