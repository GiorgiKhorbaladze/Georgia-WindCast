"use strict";

const words = {
  en: {
    title: "Wind generation", consumption: "Consumption", generation: "Total generation", import: "Imports",
    export: "Exports", hydro: "Hydro", thermal: "Thermal", wind: "Wind", solar: "Solar",
    expand: "⛶ Fullscreen", exit: "⛶ Exit fullscreen", latest: "Latest", play: "Play", pause: "Pause",
    historical: "Historical playback", recent: "Recent source period", unconfirmed: "Quality unconfirmed",
    stale: "Stale reading", unavailable: "Unavailable", trend: "24 h wind trend", source: "GSE source time",
    retrieved: "Retrieved", balance: "National balance", closure: "Difference between published balance figures",
    closureFormula: "Generation + imports − exports − consumption",
    closureNote: "Arithmetic comparison only. Measuring grid imbalance requires separate system data.",
    missingClosure: "Balance check unavailable",
    lines: "National gross total. Verified line-level records are unavailable.",
    zoomIn: "Zoom in", zoomOut: "Zoom out", reset: "Reset map", map: "Georgia geographic reference map",
    position: "Representative location", uncertainty: "uncertainty", period: "Recorded period", speed: "Playback speed",
    failure: "Could not refresh the stored readings.", close: "Close site details", previous: "vs previous 3 min",
    windUnconfirmed: "Wind reading quality unconfirmed",
    mix: "Generation mix, same source period", keys: "Map: + and − zoom, arrow keys pan, 0 resets.",
    lineData: "Per-block records (contract v1)", persistent: "unchanged value", listed: "listed by GSE, no individual record",
    testOnly: "TEST-ONLY FIXTURE: not real data, never shown in production.", noFlows: "No flow in this direction",
    block: "GSE block", zero: "0 MW",
  },
  ka: {
    title: "ქარის გენერაცია", consumption: "მოხმარება", generation: "ჯამური გენერაცია", import: "იმპორტი",
    export: "ექსპორტი", hydro: "ჰიდრო", thermal: "თბო", wind: "ქარი", solar: "მზე",
    expand: "⛶ სრულ ეკრანზე", exit: "⛶ გამოსვლა", latest: "ბოლო პერიოდი", play: "დაკვრა", pause: "პაუზა",
    historical: "ისტორიული ჩანაწერები", recent: "ბოლო პერიოდი", unconfirmed: "ხარისხი დაუდასტურებელია",
    stale: "მოძველებული", unavailable: "მიუწვდომელია", trend: "ქარი · 24 სთ", source: "GSE-ის წყაროს დრო",
    retrieved: "მიღების დრო", balance: "ეროვნული ბალანსი", closure: "გამოქვეყნებული მაჩვენებლების შეუსაბამობა",
    closureFormula: "გენერაცია + იმპორტი − ექსპორტი − მოხმარება",
    closureNote: "ეს არითმეტიკული შედარებაა. სისტემის ფიზიკური დისბალანსის დასადგენად ცალკე გაზომვებია საჭირო.",
    missingClosure: "ბალანსის შემოწმება მიუწვდომელია",
    lines: "ეროვნული ჯამი. ხაზების მიხედვით გადამოწმებული მონაცემები მიუწვდომელია.",
    zoomIn: "გადიდება", zoomOut: "შემცირება", reset: "რუკის აღდგენა", map: "საქართველოს საცნობარო რუკა",
    position: "საორიენტაციო მდებარეობა", uncertainty: "ცდომილება", period: "ჩანაწერის პერიოდი", speed: "დაკვრის სიჩქარე",
    failure: "შენახული მონაცემების განახლება ვერ მოხერხდა.", close: "ადგილის ინფორმაციის დახურვა",
    previous: "წინა 3-წუთიან პერიოდთან შედარებით", windUnconfirmed: "ქარის მონაცემის ხარისხი დაუდასტურებელია",
    mix: "გენერაციის სტრუქტურა, იგივე პერიოდი", keys: "რუკის მართვა: + / − - მასშტაბის შეცვლა; ისრები - გადაადგილება; 0 - საწყისი ხედის აღდგენა.",
    lineData: "ბლოკების მონაცემები", persistent: "უცვლელი მნიშვნელობა", listed: "GSE-ის სიაშია, ცალკე ჩანაწერი არ აქვს",
    testOnly: "მხოლოდ ტესტი: ეს რეალური მონაცემები არ არის და საიტზე არ ჩანს.", noFlows: "ამ მიმართულებით ნაკადი არ არის",
    block: "GSE-ის ბლოკი", zero: "0 MW",
  },
};
const el = id => document.getElementById(id);
const stage = el("stage");
const map = el("map");
const camera = el("camera");
const numbers = new Intl.NumberFormat("en", {maximumFractionDigits: 2});
const ns = "http://www.w3.org/2000/svg";
let data = {lang: "en", periods: [], sites: [], cities: [], outline: []};
let historicalTime = null;
let timer = null;
let view = {x: 0, y: 0, scale: 1};
let displayedGeography = null;
let fallback = null;
let selectedSite = null;

function msg(type, extra = {}) {
  window.parent.postMessage({isStreamlitMessage: true, type, ...extra}, location.origin);
}
function text(id, value) { el(id).textContent = value; }
function t(key) { return words[data.lang][key]; }
function mw(number) { return Number.isFinite(number) ? numbers.format(number) : "-"; }
function fmt(number) { return Number.isFinite(number) ? mw(number) + " MW" : "-"; }
function localTime(label) { return label ? label + " (UTC+4)" : "-"; }
function svg(tag, attrs, label) {
  const node = document.createElementNS(ns, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  if (label) node.textContent = label;
  return node;
}
function project(lon, lat) { return [566 + (lon - 43.5) * 100, 318 - (lat - 42) * 143]; }

function selectSite(group, site) {
  camera.querySelector(".active")?.classList.remove("active");
  selectedSite = group;
  group.classList.add("active");
  text("site-name", site.name);
  text("site-detail", t("position") + " · " + t("uncertainty") + " ±" + site.uncertainty + " km");
  el("site-info").hidden = false;
}
function geography() {
  camera.replaceChildren();
  el("site-info").hidden = true;
  const path = data.outline.map(ring => ring.map(([lon, lat], i) => {
    const [x, y] = project(lon, lat);
    return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
  }).join("") + "Z").join("");
  camera.append(svg("path", {d: path, class: "country", "fill-rule": "evenodd"}));
  for (const city of data.cities) {
    const [x, y] = project(city.lon, city.lat);
    camera.append(svg("circle", {cx: x, cy: y, r: 2.5, class: "city-dot"}));
    camera.append(svg("text", {x, y: y + 16, "text-anchor": "middle", class: "city"}, city[data.lang]));
  }
  for (const site of data.sites) {
    const [x, y] = project(site.lon, site.lat);
    const group = svg("g", {transform: "translate(" + x + " " + y + ")", class: "site",
      tabindex: "0", role: "button", "aria-label": site.name});
    group.append(svg("circle", {r: 13}), svg("circle", {r: 6}));
    group.append(svg("title", {}, site.name));
    group.addEventListener("click", () => selectSite(group, site));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectSite(group, site); }
    });
    camera.append(group);
  }
}
function metric(key, value) {
  const card = document.createElement("div");
  card.className = "metric";
  const label = document.createElement("span");
  const reading = document.createElement("strong");
  label.textContent = t(key);
  reading.textContent = mw(value);
  if (Number.isFinite(value)) {
    const unit = document.createElement("small");
    unit.textContent = " MW";
    reading.append(unit);
  } else reading.setAttribute("aria-label", t("unavailable"));
  card.append(label, reading);
  return card;
}
const MIX = [["hydro", "#4ea8de"], ["thermal", "#f2a65a"], ["wind", "#63dfcc"], ["solar", "#f6d860"]];
function node(tag, cls, content) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (content !== undefined) n.textContent = content;
  return n;
}
function mixbar(values) {
  const parts = MIX.map(([key, colour]) => [key, colour, values[key]]);
  const complete = parts.every(([, , v]) => Number.isFinite(v));
  el("mix-panel").hidden = !complete;
  if (!complete) return;
  const total = parts.reduce((sum, [, , v]) => sum + Math.max(0, v), 0);
  el("mixbar").replaceChildren(...parts.map(([key, colour, v]) => {
    const seg = node("span", "seg");
    seg.style.setProperty("--w", total > 0 ? (Math.max(0, v) / total * 100).toFixed(2) + "%" : "0%");
    seg.style.setProperty("--c", colour);
    seg.dataset.key = key;
    return seg;
  }));
  el("mixbar").setAttribute("aria-label", t("mix") + ": " + parts.map(([k, , v]) => t(k) + " " + fmt(v)).join(", "));
  el("mix-legend").replaceChildren(...parts.map(([key, colour, v]) => {
    const item = node("span", "mix-item");
    const dot = node("i"); dot.style.background = colour;
    item.append(dot, node("span", "", t(key)), node("b", "", mw(v)));
    return item;
  }));
}
// Contract v1 (docs/contracts/cross_border_flow_v1.md). Rendered ONLY when the document is for the
// same period and publication is authorized; production passes no document (feature gated).
function crossBorder(period) {
  const doc = data.cross_border;
  if (!doc || doc.contract !== "cross_border_flow/v1" || doc.publication !== "authorized" || !period) return null;
  const docTime = Math.round(Date.parse(doc.period?.label_utc) / 1000);
  return docTime === period.time ? doc : null;
}
function flowRow(label, record, extra) {
  const row = node("li", "flow-row");
  row.tabIndex = 0;
  row.dataset.sid = record?.source_id ?? label;
  const name = node("span", "flow-name", label);
  if (extra) name.append(node("small", "", " · " + extra));
  const value = node("b", "", record ? fmt(Math.abs(record.mw)) : "-");
  row.append(name, value);
  return row;
}
function blockRows(doc, direction) {
  const rows = [];
  for (const block of doc.blocks) {
    const records = block.lines.length ? block.lines : [block.subtotal];
    for (const r of records) {
      if (r.direction !== direction) continue;
      const label = r.kind === "line" ? r.identifier + " (" + block.block_country_label + ")" : block.block_country_label + " · " + t("block");
      const extra = r.availability === "persistent_value" ? t("persistent")
        : r.published_line ? r.published_line.voltage_kv + " kV" : "";
      const row = flowRow(label, r, extra);
      if (r.availability === "persistent_value") row.classList.add("persistent");
      rows.push(row);
    }
  }
  return rows;
}
function interchange(panel, key, period) {
  const article = el(panel);
  const heading = node("h2", "", t(key));
  const value = node("strong", "", fmt(period?.values[key]));
  const children = [heading, value];
  const doc = crossBorder(period);
  if (doc) {
    const list = node("ul", "flows");
    list.setAttribute("aria-label", t(key) + " · " + t("lineData"));
    const rows = blockRows(doc, key);
    if (rows.length) list.append(...rows); else list.append(node("li", "flow-empty", t("noFlows")));
    children.push(node("p", "flow-caption", t("lineData")), list);
  }
  article.replaceChildren(...children);
}
function linkHighlight() {
  for (const row of document.querySelectorAll(".flow-row")) {
    const on = () => document.querySelectorAll(`.flow-row[data-sid="${row.dataset.sid}"]`).forEach(r => r.classList.add("hot"));
    const off = () => document.querySelectorAll(".flow-row.hot").forEach(r => r.classList.remove("hot"));
    row.addEventListener("pointerenter", on); row.addEventListener("pointerleave", off);
    row.addEventListener("focus", on); row.addEventListener("blur", off);
  }
}
function sparkline(index) {
  const history = data.periods.slice(0, index + 1);
  const first = data.periods[0]?.time ?? 0;
  const end = data.periods.at(-1)?.time ?? first;
  const values = history.map(p => p.values.wind).filter(Number.isFinite);
  const low = Math.min(...values), scale = Math.max(Math.max(...values) - low, 1);
  let last = null;
  const path = history.map(period => {
    if (!Number.isFinite(period.values.wind)) { last = null; return ""; }
    const command = last !== null && period.time - last === 180 ? "L" : "M";
    last = period.time;
    const x = (period.time - first) * 276 / Math.max(end - first, 1) + 2;
    const y = 44 - (period.values.wind - low) * 40 / scale;
    return command + x.toFixed(1) + "," + y.toFixed(1);
  }).join("");
  el("spark").setAttribute("d", path);
}
function indexOfPeriod() {
  if (historicalTime === null) return data.periods.length - 1;
  const index = data.periods.findIndex(period => period.time >= historicalTime);
  return index < 0 ? data.periods.length - 1 : index;
}
function readings() {
  const index = indexOfPeriod();
  const period = data.periods[index];
  const prev = data.periods[index - 1];
  const values = period?.values ?? {};
  let status = period?.status ?? "unavailable";
  if (historicalTime !== null && period) status = "historical";
  else if (period && period.time * 1000 < Date.now() - 600000) status = "stale";
  text("mode", t(status));
  el("mode").dataset.status = status;
  text("wind", mw(values.wind));
  el("wind").nextElementSibling.hidden = !Number.isFinite(values.wind);
  text("source-time", t("source") + " · " + localTime(period?.label));
  const windUnconfirmed = Boolean(period && Number.isFinite(values.wind) && !period.wind_confirmed);
  text("wind-quality", t("windUnconfirmed"));
  el("wind-quality").hidden = !windUnconfirmed;
  text("trend-label", t("trend"));
  const comparable = prev && period.time - prev.time === 180 && period.wind_confirmed && prev.wind_confirmed &&
    Number.isFinite(values.wind) && Number.isFinite(prev.values.wind);
  const delta = comparable ? values.wind - prev.values.wind : null;
  text("delta", delta === null ? "" : (delta > 0 ? "+" : "") + fmt(delta));
  el("delta").title = t("previous");
  sparkline(index);
  el("national").replaceChildren(...["consumption", "generation", "import", "export"].map(k => metric(k, values[k])));
  el("mix").replaceChildren(...["hydro", "thermal", "wind", "solar"].map(k => metric(k, values[k])));
  text("retrieved", t("retrieved") + " · " + localTime(period?.retrieved));
  const residual = period?.residual;
  const hasBalance = Number.isFinite(residual);
  const signedDifference = hasBalance && residual >= .005 ? "+" + fmt(residual) : fmt(residual);
  text("closure", hasBalance ? t("closure") + " · " : t("missingClosure"));
  if (hasBalance) {
    const amount = document.createElement("span");
    amount.className = "reconciliation-amount";
    amount.textContent = signedDifference;
    el("closure").append(amount);
  }
  el("closure").title = hasBalance ? t("closureFormula") : "";
  text("closure-note", t("closureNote"));
  el("closure-note").hidden = !hasBalance;
  mixbar(values);
  interchange("imports", "import", period);
  interchange("exports", "export", period);
  linkHighlight();
  text("test-only", t("testOnly"));
  el("test-only").hidden = !(data.cross_border && data.cross_border.test_only);
  const slider = el("time");
  slider.max = Math.max(data.periods.length - 1, 0);
  slider.value = Math.max(0, index);
  slider.setAttribute("aria-valuetext", localTime(period?.label));
  slider.disabled = data.periods.length < 2;
  el("play").disabled = data.periods.length < 2;
  el("latest").disabled = historicalTime === null;
  text("play", t(timer === null ? "play" : "pause"));
}
function selectIndex(index) {
  historicalTime = data.periods[index]?.time ?? null;
  readings();
}
function stopPlayback() {
  clearInterval(timer);
  timer = null;
}
function startPlayback() {
  if (data.periods.length < 2) return;
  if (historicalTime === null || indexOfPeriod() >= data.periods.length - 1) selectIndex(0);
  timer = setInterval(() => {
    const next = indexOfPeriod() + 1;
    if (next >= data.periods.length - 1) {
      stopPlayback();
      selectIndex(data.periods.length - 1);
    } else selectIndex(next);
  }, 950 / Number(el("speed").value));
  readings();
}
el("play").onclick = () => {
  if (timer === null) startPlayback();
  else { stopPlayback(); readings(); }
};
el("latest").onclick = () => { stopPlayback(); historicalTime = null; readings(); };
el("time").oninput = event => { stopPlayback(); selectIndex(Number(event.target.value)); };
el("speed").onchange = () => { if (timer !== null) { stopPlayback(); startPlayback(); } };

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
let animation = null;
function moveCamera() {
  camera.setAttribute("transform", `translate(${view.x} ${view.y}) scale(${view.scale})`);
}
function animateTo(target) {
  cancelAnimationFrame(animation);
  if (reduceMotion.matches) { view = target; moveCamera(); return; }
  const from = {...view}, start = performance.now(), duration = 260;
  const step = now => {
    const k = Math.min(1, (now - start) / duration), e = 1 - Math.pow(1 - k, 3);
    view = {x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e,
      scale: from.scale + (target.scale - from.scale) * e};
    moveCamera();
    if (k < 1) animation = requestAnimationFrame(step);
  };
  animation = requestAnimationFrame(step);
}
function zoomTarget(factor, center = {x: 540, y: 318}) {
  const scale = Math.max(.85, Math.min(8, view.scale * factor));
  const ratio = scale / view.scale;
  return {x: center.x - (center.x - view.x) * ratio, y: center.y - (center.y - view.y) * ratio, scale};
}
function zoom(factor, center = {x: 540, y: 318}) {
  const scale = Math.max(.85, Math.min(8, view.scale * factor));
  const ratio = scale / view.scale;
  view.x = center.x - (center.x - view.x) * ratio;
  view.y = center.y - (center.y - view.y) * ratio;
  view.scale = scale;
  moveCamera();
}
function point(event) {
  return new DOMPoint(event.clientX, event.clientY).matrixTransform(map.getScreenCTM().inverse());
}
const pointers = new Map();
map.addEventListener("wheel", event => { event.preventDefault(); zoom(Math.exp(-event.deltaY / 550), point(event)); },
  {passive: false});
map.addEventListener("pointerdown", event => {
  if (event.button !== 0 || event.target.closest(".site")) return;
  map.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, point(event));
});
map.addEventListener("pointermove", event => {
  const previous = pointers.get(event.pointerId);
  if (!previous) return;
  const current = point(event);
  const other = [...pointers].find(([id]) => id !== event.pointerId)?.[1];
  if (other) {
    const oldDistance = Math.hypot(previous.x - other.x, previous.y - other.y);
    const newDistance = Math.hypot(current.x - other.x, current.y - other.y);
    if (oldDistance && newDistance) zoom(newDistance / oldDistance, other);
  } else {
    view.x += current.x - previous.x;
    view.y += current.y - previous.y;
    moveCamera();
  }
  pointers.set(event.pointerId, current);
});
for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
  map.addEventListener(name, event => pointers.delete(event.pointerId));
}
el("plus").onclick = () => animateTo(zoomTarget(1.27));
el("minus").onclick = () => animateTo(zoomTarget(1 / 1.27));
el("reset").onclick = () => animateTo({x: 0, y: 0, scale: 1});
map.addEventListener("keydown", event => {
  const pan = 40;
  const moves = {ArrowLeft: [pan, 0], ArrowRight: [-pan, 0], ArrowUp: [0, pan], ArrowDown: [0, -pan]};
  if (event.key === "+" || event.key === "=") animateTo(zoomTarget(1.27));
  else if (event.key === "-" || event.key === "_") animateTo(zoomTarget(1 / 1.27));
  else if (event.key === "0") animateTo({x: 0, y: 0, scale: 1});
  else if (moves[event.key]) animateTo({...view, x: view.x + moves[event.key][0], y: view.y + moves[event.key][1]});
  else return;
  event.preventDefault();
});
el("close-site").onclick = () => {
  el("site-info").hidden = true;
  selectedSite?.classList.remove("active");
  selectedSite?.focus();
};

function immersive(active) {
  if (!active) {
    if (!fallback) return;
    if (fallback.frame) fallback.frame.style.cssText = fallback.style;
    fallback.body.style.overflow = fallback.overflow;
    fallback = null;
    stage.classList.remove("immersive");
    return;
  }
  let frame;
  try { frame = window.frameElement; } catch { frame = null; }
  const body = frame?.ownerDocument.body ?? document.body;
  fallback = {frame, style: frame?.style.cssText, body, overflow: body.style.overflow};
  body.style.overflow = "hidden";
  if (frame) {
    for (const [prop, value] of Object.entries({
      position: "fixed", inset: "0", width: "100vw", height: "100dvh", "z-index": "2147483647", background: "#091421",
    })) frame.style.setProperty(prop, value, "important");
  }
  stage.classList.add("immersive");
}
function fullscreenState() {
  return document.fullscreenElement === stage ? "native" : fallback ? "immersive" : "normal";
}
function fullscreenLabel() {
  const state = fullscreenState();
  stage.dataset.fullscreen = state;
  text("expand", t(state === "normal" ? "expand" : "exit"));
  el("expand").setAttribute("aria-pressed", String(state !== "normal"));
}
el("expand").onclick = async () => {
  if (document.fullscreenElement === stage) await document.exitFullscreen();
  else if (fallback) immersive(false);
  else {
    try {
      if (!document.fullscreenEnabled || !stage.requestFullscreen) throw new Error("Fullscreen unavailable");
      await stage.requestFullscreen();
    } catch { immersive(true); }
  }
  fullscreenLabel();
};
document.addEventListener("fullscreenchange", fullscreenLabel);
document.addEventListener("keydown", async event => {
  if (event.key !== "Escape") return;
  if (fallback) {
    immersive(false);
    fullscreenLabel();
  } else if (document.fullscreenElement === stage) {
    await document.exitFullscreen();
  }
});
window.addEventListener("pagehide", () => {
  immersive(false);
  if (sameOriginParent) sameOriginParent.removeEventListener("resize", resize);
});

function resize() {
  const mobile = innerWidth < 590;
  map.setAttribute("viewBox", mobile ? "180 -65 770 690" : "0 0 1000 590");
  let parentHeight = screen.availHeight;
  try { parentHeight = window.parent.innerHeight; } catch { /* cross-origin iframe */ }
  stage.style.setProperty("--map-height", Math.round(parentHeight * .78) + "px");
  if (fullscreenState() === "normal") {
    const height = Math.ceil(document.querySelector("main").getBoundingClientRect().height);
    if (height !== resize.lastHeight) { resize.lastHeight = height; msg("streamlit:setFrameHeight", {height}); }
  }
}
function render(args) {
  data = args;
  const geoKey = JSON.stringify([data.lang, data.sites]);
  if (geoKey !== displayedGeography) { geography(); displayedGeography = geoKey; }
  document.documentElement.lang = data.lang;
  text("heading", t("title"));
  text("latest", t("latest"));
  text("balance-heading", t("balance"));
  text("fetch-status", t("failure"));
  el("fetch-status").hidden = !data.refresh_failed;
  for (const [id, key] of Object.entries({map: "map", trend: "trend", plus: "zoomIn", minus: "zoomOut",
      reset: "reset", "close-site": "close", time: "period", speed: "speed"})) {
    el(id).setAttribute("aria-label", t(key));
  }
  text("map-keys", t("keys"));
  readings();
  fullscreenLabel();
  resize();
}
window.addEventListener("message", event => {
  if (event.source === window.parent && event.origin === location.origin && event.data?.type === "streamlit:render") {
    render(event.data.args);
  }
});
// A height-only change in the host window may leave the iframe dimensions untouched.
let sameOriginParent = null;
try {
  if (window.parent !== window && window.parent.location.origin === location.origin) {
    sameOriginParent = window.parent;
    sameOriginParent.addEventListener("resize", resize);
  }
} catch { /* native fullscreen and child resize remain available */ }
new ResizeObserver(resize).observe(document.querySelector("main"));
// Site details sit just above the bottom dock (metrics, mix, playback), whatever its height.
const dock = document.querySelector(".stage-bottom");
new ResizeObserver(() => el("stage").style.setProperty("--dock", dock.offsetHeight + "px")).observe(dock);
window.addEventListener("resize", resize);
setInterval(() => { if (timer === null && data.periods.length) readings(); }, 30000);
msg("streamlit:componentReady", {apiVersion: 1});
