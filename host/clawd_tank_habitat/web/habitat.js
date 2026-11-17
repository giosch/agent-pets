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
  const pet = { el, image, badge, helpers, moment: "", timer: 0 };
  pets.set(id, pet);
  return pet;
}

function clearMoment(pet) {
  clearTimeout(pet.timer);
  pet.moment = "";
  delete pet.el.dataset.moment;
}

function paint(session, moment) {
  const pet = pets.get(session.id) || newPet(session.id);
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
  const pose = pet.moment || attention || session.activity;
  const src = "/art/character/" + selectors.character.value + "/" + pose + "?variant=" + session.order;
  if (pet.image.getAttribute("src") !== src) pet.image.setAttribute("src", src);
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
  symbol(pet.helpers, session.helpers ? "helpers" : "", session.helpers + " helpers");
  return pet.el;
}

function render(momentId, moment) {
  const ranked = [...sessions.values()].sort((a, b) => priority(a) - priority(b) || a.order - b.order);
  const visible = ranked.slice(0, capacity);
  if (!visible.length) visible.push({ id: "", order: 0, activity: "resting", attention: "none", helpers: 0 });
  const ids = new Set(visible.map(s => s.id));
  for (const [id, pet] of pets) {
    if (ids.has(id)) continue;
    clearMoment(pet);
    pet.el.remove();
    pets.delete(id);
  }
  visible.forEach((session, index) => {
    const el = paint(session, session.id === momentId ? moment : "");
    const current = occupants.children[index];
    if (current !== el) occupants.insertBefore(el, current || null);
  });
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
  for (const pack of catalog.packs) selectors[pack.kind].add(new Option(pack.name, pack.id));
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
      for (const pet of pets.values()) clearMoment(pet);
      for (const session of message.sessions) sessions.set(session.id, session);
      connected = true;
      connection(demo ? "demo" : "live", demo ? "Demo" : "Live");
    } else {
      if (message.sequence <= sequence) return;
      if (message.type === "remove") sessions.delete(message.id);
      if (message.type === "update") sessions.set(message.session.id, message.session);
    }
    sequence = message.sequence;
    render(message.session?.id, message.moment);
  };
  events.onerror = () => {
    connected = false;
    byId("empty-help").hidden = true;
    connection("offline", "Reconnecting");
  };
}
start().catch(() => connection("error", "Unable to load habitat"));
