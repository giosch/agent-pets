const byId = id => document.getElementById(id);
const occupants = byId("occupants");
const sessions = new Map();
const pets = new Map();
const capacity = 3;
const blocking = new Set(["approval", "question", "failure"]);
const labels = { approval: "Needs approval", question: "Needs an answer", failure: "Needs intervention", ready: "Turn ready" };
const selectors = { character: byId("character"), habitat: byId("habitat") };
const defaults = { character: "clawd", habitat: "tidal" };
const preferenceKey = "clawd-tank.habitat.appearance.v1";
let sequence = -1;
let demo = false;
let connected = false;
let lowPower = false;
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const compact = matchMedia("(max-width: 480px)");
const artwork = new Map();
const departures = new Map();

const idlePoses = ["coffee", "groove", "hat"];

function art(pose, order) {
  return "/art/character/" + selectors.character.value + "/" + pose + "?variant=" + order;
}

function supports(pose) {
  return artwork.get(selectors.character.value)?.has(pose);
}

function leave(id, pet, closed) {
  const pose = closed ? "departing" : "walking";
  if (motion.matches || !supports(pose)) return;
  departures.get(id)?.remove();
  const scene = byId("scene");
  const box = pet.el.getBoundingClientRect();
  const parent = scene.getBoundingClientRect();
  const ghost = document.createElement("img");
  ghost.alt = "";
  ghost.className = "leaving " + pose;
  ghost.src = art(pose, pet.el.dataset.palette);
  Object.assign(ghost.style, { left: box.left - parent.left + "px", top: box.top - parent.top + "px",
    width: box.width + "px", height: box.height + "px" });
  scene.append(ghost);
  departures.set(id, ghost);
  setTimeout(() => {
    ghost.remove();
    if (departures.get(id) === ghost) departures.delete(id);
  }, closed ? 3000 : 650);
}

function priority(session) {
  if (blocking.has(session.attention)) return 0;
  return session.attention === "ready" ? 1 : 2;
}

function connection(state, text) {
  byId("connection").dataset.state = state;
  byId("connection").querySelector("span").textContent = text;
}

function symbol(holder, kind, title) {
  if (holder.dataset.kind === kind) return;
  holder.dataset.kind = kind;
  holder.hidden = !kind;
  holder.title = title;
  if (!kind) return;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", "#s-" + kind);
  svg.append(use);
  svg.setAttribute("aria-hidden", "true");
  holder.replaceChildren(svg);
}

function newPet(id) {
  const el = document.createElement("div");
  el.className = "pet";
  el.setAttribute("role", "img");
  const image = document.createElement("img");
  image.alt = "";
  const badge = document.createElement("span");
  badge.className = "signal";
  const helpers = document.createElement("span");
  helpers.className = "helpers";
  el.append(image, badge, helpers);
  const companion = document.createElement("img");
  companion.className = "companion";
  companion.alt = "";
  const details = document.createElement("span");
  details.append(companion);
  el.append(details);
  const pet = { el, image, badge, helpers, companion, moment: "", timer: 0, phase: "", since: 0,
    failures: [], completions: 0, previous: "", travelUntil: 0, offlineImage: null };
  pets.set(id, pet);
  return pet;
}

function clearMoment(pet) {
  clearTimeout(pet.timer);
  pet.moment = "";
  delete pet.el.dataset.moment;
}

function paint(session, moment, travel) {
  const pet = pets.get(session.id) || newPet(session.id);
  const now = Date.now();
  const phase = session.activity + "/" + session.attention;
  if (phase !== pet.phase) { pet.phase = phase; pet.since = now; }
  if (moment === "setback") pet.failures = pet.failures.filter(t => now - t < 30000).concat(now);
  if (moment === "completed") pet.completions++;
  if (travel) { pet.travel = travel; pet.travelUntil = now + (travel === "wake" ? 1500 : 650); }
  if (session.attention !== "none" || !connected || (!travel && pet.previous !== phase)) pet.travelUntil = 0;
  pet.previous = phase;
  // An actionable alert always takes precedence over a fleeting reaction.
  if (blocking.has(session.attention) || (pet.moment === "completed" && session.attention !== "ready")) {
    clearMoment(pet);
  }
  else if (moment) {
    clearMoment(pet);
    pet.moment = moment;
    pet.el.dataset.moment = moment;
    pet.timer = setTimeout(() => { clearMoment(pet); render(); }, 1450);
  }
  const attention = labels[session.attention] ? session.attention : "";
  const resting = session.id === "";
  const elapsed = now - pet.since;
  let pose = session.activity;
  if (pose === "idle" && elapsed >= 12000 && elapsed % 12000 < 3200)
    pose = idlePoses[(Math.floor(elapsed / 12000) - 1 + session.order) % idlePoses.length];
  if (pose === "working" && elapsed >= 10000) pose = Math.floor(elapsed / 10000) % 2 ? "thinking" : "pushing";
  if (compact.matches && !["idle", "resting"].includes(session.activity)) pose = "compact_work";
  if (session.active_calls > 1) pose = "parallel";
  if (lowPower && ["idle", "resting"].includes(session.activity)) pose = "low_power";
  if (pet.travelUntil > now) pose = pet.travel;
  if (attention) pose = attention;
  if (pet.moment) {
    pose = pet.moment === "forked" ? session.activity : pet.moment;
    if (pet.moment === "completed" && pet.completions % 2 === 0) pose = "eureka";
    if (pet.moment === "setback" && pet.failures.length >= 2) pose = "overheated";
  }
  if (!connected && sequence >= 0) pose = "offline";
  if (motion.matches && supports("still")) pose = "still";
  if (!supports(pose) && !["working","editing","executing","researching","inspecting","external",
      "coordinating","question","failure","approval","ready","completed","setback","interrupted","compacted",
      "idle","resting"].includes(pose)) pose = attention || session.activity;
  const src = art(pose, session.order);
  const cached = pet.offlineImage;
  if (pose === "offline" && cached?.naturalWidth && pet.image !== cached) {
    pet.el.replaceChild(cached, pet.image);
    pet.image = cached;
  } else if (pet.image === cached && pose !== "offline") {
    const image = new Image();
    image.alt = "";
    pet.el.replaceChild(image, cached);
    pet.image = image;
  }
  if (pet.image.getAttribute("src") !== src) pet.image.setAttribute("src", src);
  pet.el.style.setProperty("--fork-art", "url('" + src + "')");
  pet.el.dataset.session = session.id;
  pet.el.dataset.pose = pose;
  pet.el.dataset.palette = String(session.order);
  pet.el.toggleAttribute("data-resting", resting);
  const description = resting ? "Habitat resting" : "Pet " + (session.order + 1) + ", " +
    session.activity + (attention ? ", " + labels[attention] : "") +
    (session.helpers ? ", " + session.helpers + " helpers" : "");
  pet.el.setAttribute("aria-label", description);
  pet.el.title = description;
  symbol(pet.badge, attention, labels[attention] || "");
  const companion = session.helpers > 0 && supports("helper") && !motion.matches;
  pet.companion.hidden = !companion;
  if (companion && pet.companion.getAttribute("src") !== art("helper", session.order))
    pet.companion.src = art("helper", session.order);
  symbol(pet.helpers, session.helpers && !companion ? "helpers" : "", session.helpers + " helpers");
  if (connected && supports("offline") && cached?.getAttribute("src") !== art("offline", session.order)) {
    pet.offlineImage = new Image();
    pet.offlineImage.alt = "";
    pet.offlineImage.src = art("offline", session.order);
  }
  return pet.el;
}

function render(momentId, moment, live = false) {
  const wasEmpty = pets.has("");
  const positions = new Map([...pets].map(([id, p]) => [id, p.el.offsetLeft]));
  const ranked = [...sessions.values()].sort((a, b) => priority(a) - priority(b) || a.order - b.order);
  const visible = ranked.slice(0, capacity);
  if (!visible.length) visible.push({ id: "", order: 0, activity: "resting", attention: "none", helpers: 0 });
  const ids = new Set(visible.map(s => s.id));
  if (moment === "forked" && !ids.has(momentId) && !motion.matches) {
    const overflow = byId("overflow");
    const echo = document.createElement("span");
    echo.className = "fork-flash";
    echo.setAttribute("aria-hidden", "true");
    echo.style.setProperty("--fork-art", "url('" + art("idle", sessions.get(momentId).order) + "')");
    overflow.append(echo);
    setTimeout(() => echo.remove(), 1450);
  }
  for (const [id, pet] of pets) {
    if (ids.has(id)) continue;
    if (id && live) leave(id, pet, !sessions.has(id));
    clearMoment(pet);
    pet.el.remove();
    pets.delete(id);
  }
  visible.forEach((session, index) => {
    departures.get(session.id)?.remove();
    const travel = live && session.id && !pets.has(session.id) ? (wasEmpty ? "wake" : "walking") : "";
    const el = paint(session, session.id === momentId ? moment : "", travel);
    const current = occupants.children[index];
    if (current !== el) occupants.insertBefore(el, current || null);
  });
  if (live && !motion.matches) for (const session of visible) {
    const pet = pets.get(session.id);
    const delta = positions.has(session.id) ? positions.get(session.id) - pet.el.offsetLeft : 0;
    if (delta) {
      pet.el.animate([{transform: "translateX(" + delta + "px)"}, {transform:"none"}], 650);
      paint(session, "", "walking");
    }
  }
  const extra = Math.max(0, ranked.length - capacity);
  byId("overflow").hidden = !extra;
  byId("overflow").title = extra + " additional sessions";
  byId("overflow").setAttribute("role", "img");
  byId("overflow").setAttribute("aria-label", byId("overflow").title);
  byId("session-count").textContent = ranked.length + (ranked.length === 1 ? " session" : " sessions") +
    (extra ? " · " + capacity + " in view" : "");
  byId("empty-help").hidden = !connected || demo || ranked.length > 0;
}

function applyAppearance() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(preferenceKey)) || {}; } catch {}
  for (const [kind, select] of Object.entries(selectors)) {
    const options = [...select.options].map(option => option.value);
    select.value = options.includes(saved[kind]) ? saved[kind] : defaults[kind];
  }
  byId("landscape").src = "/art/habitat/" + selectors.habitat.value + "/scene";
  byId("scene").setAttribute("aria-label", selectors.habitat.selectedOptions[0].textContent);
  render();
}

async function start() {
  const response = await fetch("/v1/themes");
  if (!response.ok) throw new Error("Theme catalog unavailable");
  const catalog = await response.json();
  demo = catalog.demo;
  for (const pack of catalog.packs) {
    selectors[pack.kind].add(new Option(pack.name, pack.id));
    if (pack.kind === "character") artwork.set(pack.id, new Set(pack.poses));
  }
  motion.addEventListener("change", () => render());
  compact.addEventListener("change", () => render());
  setInterval(() => { if (connected && !document.hidden) render(); }, 500);
  navigator.getBattery?.().then(battery => {
    function power() { lowPower = !battery.charging && battery.level <= .15; render(); }
    power();
    battery.addEventListener("chargingchange", power);
    battery.addEventListener("levelchange", power);
  }).catch(() => {});
  applyAppearance();
  for (const select of Object.values(selectors)) {
    select.addEventListener("change", () => {
      const choices = { character: selectors.character.value, habitat: selectors.habitat.value };
      try { localStorage.setItem(preferenceKey, JSON.stringify(choices)); } catch {}
      byId("landscape").src = "/art/habitat/" + choices.habitat + "/scene";
      byId("scene").setAttribute("aria-label", selectors.habitat.selectedOptions[0].textContent);
      render();
    });
  }
  window.addEventListener("storage", event => { if (event.key === preferenceKey) applyAppearance(); });
  const events = new EventSource("/v1/events");
  events.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.version !== 1) {
      events.close();
      connection("error", "Incompatible host");
      return;
    }
    if (message.type === "snapshot") {
      sessions.clear();
      for (const pet of pets.values()) { clearMoment(pet); pet.travelUntil = 0; pet.failures = []; }
      for (const ghost of departures.values()) ghost.remove();
      departures.clear();
      for (const session of message.sessions) sessions.set(session.id, session);
      connected = true;
      connection(demo ? "demo" : "live", demo ? "Demo" : "Live");
    } else {
      if (message.sequence <= sequence) return;
      if (message.type === "remove") sessions.delete(message.id);
      if (message.type === "update") sessions.set(message.session.id, message.session);
    }
    sequence = message.sequence;
    render(message.session?.id, message.moment, message.type !== "snapshot");
  };
  events.onerror = () => {
    connected = false;
    byId("empty-help").hidden = true;
    connection("offline", "Reconnecting");
    render();
  };
}
start().catch(() => connection("error", "Unable to load habitat"));
