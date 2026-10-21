"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const enc = encodeURIComponent;
const PLOTLY_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js";

const state = {
  info: null,
  projects: [],
  project: localStorage.getItem("pm.project"),
  prop: localStorage.getItem("pm.prop"),
  cam: 1,
  tab: localStorage.getItem("pm.tab") || "project",
  projectData: null,
  status: null,
  camera: null,
  job: null,
  align: { spread: null },
  mask: { points: [], dirty: false },
  review: { items: [], total: 0, index: 0, detected: false, polygon: null, meta: {} },
};

// ----------------------------------------------------------------------------- helpers

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
}

let toastTimer = null;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), isError ? 6000 : 3000);
}

function on(el, event, fn) {
  if (typeof el === "string") el = $(el);
  el.addEventListener(event, async (e) => {
    try { await fn(e); } catch (err) { toast(err.message, true); }
  });
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

const propUrl = (suffix = "") => `/api/projects/${enc(state.project)}/props/${enc(state.prop)}${suffix}`;
const camUrl = (suffix = "") => propUrl(`/cams/${state.cam}${suffix}`);
const settings = () => (state.status ? state.status.settings : null);
const totalPixels = () => (state.status ? state.status.total_pixels : 0);
const camStatus = () => (state.status ? state.status.cams[state.cam - 1] : null);

function frameSize() {
  if (state.camera && state.camera.frame_size) return state.camera.frame_size;
  const cs = camStatus();
  if (cs && cs.meta && cs.meta.image_size) return cs.meta.image_size;
  return settings() ? settings().image_size : [1920, 1080];
}

function canvasPoint(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  return [
    ((e.clientX - rect.left) / rect.width) * canvas.width,
    ((e.clientY - rect.top) / rect.height) * canvas.height,
  ];
}

function line(g, x1, y1, x2, y2, color, width) {
  g.strokeStyle = color;
  g.lineWidth = width;
  g.beginPath();
  g.moveTo(x1, y1);
  g.lineTo(x2, y2);
  g.stroke();
}

function pixelLocation(index) {
  for (const u of (state.status ? state.status.layout : [])) {
    if (index >= u.first_pixel && index < u.first_pixel + u.pixels) {
      const local = index - u.first_pixel;
      return `universe ${u.universe}, channel ${local * 3 + 1}`;
    }
  }
  return "";
}

function promptName(title, extraHtml = "") {
  const dlg = $("#nameDialog");
  $("#nameDialogTitle").textContent = title;
  $("#nameDialogInput").value = "";
  $("#nameDialogExtra").innerHTML = extraHtml;
  dlg.showModal();
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => {
      if (dlg.returnValue !== "ok") return resolve(null);
      const extra = {};
      $$("[name]", $("#nameDialogExtra")).forEach((el) => { extra[el.name] = el.value; });
      resolve({ name: $("#nameDialogInput").value.trim(), ...extra });
    }, { once: true });
  });
}

// ----------------------------------------------------------------------------- loading

async function loadProjects() {
  state.projects = await api("GET", "/api/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = state.projects.map((p) => `<option>${escapeHtml(p)}</option>`).join("");
  if (!state.projects.includes(state.project)) state.project = state.projects[0] || null;
  sel.value = state.project || "";
  $("#noProject").classList.toggle("hidden", !!state.project);
  await loadProject();
}

async function loadProject() {
  if (!state.project) {
    state.projectData = null;
    state.prop = null;
  } else {
    localStorage.setItem("pm.project", state.project);
    state.projectData = await api("GET", `/api/projects/${enc(state.project)}`);
    const props = Object.keys(state.projectData.props);
    if (!props.includes(state.prop)) state.prop = props[0] || null;
    $("#propSelect").innerHTML = props.map((p) => `<option>${escapeHtml(p)}</option>`).join("");
    $("#propSelect").value = state.prop || "";
  }
  await loadProp();
}

async function loadProp() {
  if (state.prop) localStorage.setItem("pm.prop", state.prop);
  state.status = state.project && state.prop ? await api("GET", propUrl()) : null;
  const ncam = state.status ? state.status.cams.length : 0;
  if (state.cam > ncam) state.cam = 1;
  document.body.classList.toggle("mode-2d", !!state.status && state.status.settings.mode === "2d");
  renderCamButtons();
  renderProject();
  enterTab(state.tab);
}

async function refreshStatus() {
  if (state.project && state.prop) state.status = await api("GET", propUrl());
}

function renderCamButtons() {
  const n = state.status ? state.status.cams.length : 0;
  $("#camPicker").classList.toggle("hidden", n === 0);
  $("#camButtons").innerHTML = Array.from({ length: n }, (_, i) =>
    `<button class="small ${i + 1 === state.cam ? "active" : ""}" data-cam="${i + 1}">${i + 1}</button>`).join("");
  $$("#camButtons button").forEach((b) => b.addEventListener("click", () => {
    state.cam = Number(b.dataset.cam);
    state.mask.dirty = false;
    renderCamButtons();
    enterTab(state.tab);
  }));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ----------------------------------------------------------------------------- tabs

function showTab(tab) {
  state.tab = tab;
  localStorage.setItem("pm.tab", tab);
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab").forEach((s) => s.classList.toggle("hidden", s.id !== `tab-${tab}`));
  enterTab(tab);
}

function enterTab(tab) {
  const needsProp = tab !== "project";
  document.body.classList.toggle("no-prop", !state.status);
  $("#noProp").classList.toggle("hidden", !(needsProp && state.project && !state.status));
  updateStreams();
  if (needsProp && !state.status) return;
  try {
    if (tab === "lights") enterLights();
    else if (tab === "align") enterAlign();
    else if (tab === "capture") enterCapture();
    else if (tab === "review") loadDetections().catch((e) => toast(e.message, true));
    else if (tab === "model") enterModel().catch((e) => toast(e.message, true));
  } catch (err) {
    toast(err.message, true);
  }
}

// ----------------------------------------------------------------------------- camera

async function refreshCamera() {
  state.camera = await api("GET", "/api/camera");
  const c = state.camera;
  $("#cameraStatus").textContent = c.open
    ? `Open: source ${c.source}, ${c.frame_size[0]} x ${c.frame_size[1]}` +
      (c.requested_size && (c.requested_size[0] !== c.frame_size[0] || c.requested_size[1] !== c.frame_size[1])
        ? ` (asked for ${c.requested_size[0]} x ${c.requested_size[1]})` : "")
    : c.error || "Closed. Not needed on a computer that only reviews and builds models.";
  updateStreams();
}

function updateStreams() {
  const open = state.camera && state.camera.open;
  $$(".tab").forEach((section) => {
    const visible = !section.classList.contains("hidden") && !!state.status;
    const closed = $(".camera-closed", section);
    if (closed) closed.classList.toggle("hidden", open || !visible);
    const live = $(".live", section);
    if (live) live.classList.toggle("hidden", !open);
    const img = $("img.stream", section);
    if (!img) return;
    if (visible && open) {
      if (!img.getAttribute("src")) {
        img.src = `/api/camera/stream?w=960&t=${Date.now()}`;
        img.onload = () => redrawOverlays();
      }
    } else if (img.getAttribute("src")) {
      img.removeAttribute("src");
    }
  });
}

async function openCamera() {
  const source = $("#cameraSource").value.trim() || "0";
  const size = settings() ? settings().image_size : [1920, 1080];
  toast("Opening camera...");
  await api("POST", "/api/camera/open", { source, size });
  await refreshCamera();
  toast("Camera open");
  enterTab(state.tab);
}

function redrawOverlays() {
  if (state.tab === "align") drawAlign();
  if (state.tab === "capture") drawMask();
}

// ----------------------------------------------------------------------------- project tab

function renderProject() {
  const form = $("#propForm");
  form.closest(".card").classList.toggle("hidden", !state.status);
  if (!state.status) {
    $("#propSummary").innerHTML = state.project
      ? `<p>Add a prop with <b>New</b> next to Prop: the tree, a bush, and so on.</p>`
      : "";
    return;
  }
  fillPropForm(state.status.settings);
  renderSummary();
}

function fillPropForm(s) {
  const f = $("#propForm");
  f.mode.value = s.mode;
  f.controller_ip.value = s.controller_ip;
  f.image_w.value = s.image_size[0];
  f.image_h.value = s.image_size[1];
  f.distance.value = s.distance;
  f.fov_h.value = s.fov[0];
  f.fov_v.value = s.fov[1];
  f.on_color.value = "#" + s.on_color.map((v) => v.toString(16).padStart(2, "0")).join("");
  f.settle_ms.value = s.settle_ms;
  $("#universeRows").innerHTML = "";
  s.universes.forEach((u) => addUniverseRow(u.universe, u.channels));
  updatePixelTotal();
}

function addUniverseRow(universe, channels) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input type="number" class="u-num" min="1" max="63999" value="${universe}"></td>
    <td><input type="number" class="u-ch" min="3" max="512" value="${channels}"></td>
    <td class="u-px"></td><td><button type="button" class="small danger">Remove</button></td>`;
  $("button", tr).addEventListener("click", () => { tr.remove(); updatePixelTotal(); });
  $(".u-ch", tr).addEventListener("input", updatePixelTotal);
  $("#universeRows").appendChild(tr);
}

function updatePixelTotal() {
  let total = 0;
  $$("#universeRows tr").forEach((tr) => {
    const px = Math.floor((Number($(".u-ch", tr).value) || 0) / 3);
    $(".u-px", tr).textContent = px;
    total += px;
  });
  $("#pixelTotal").textContent = `${total} pixels total`;
}

function readPropForm() {
  const f = $("#propForm");
  const hex = f.on_color.value.replace("#", "");
  return {
    mode: f.mode.value,
    controller_ip: f.controller_ip.value.trim(),
    universes: $$("#universeRows tr").map((tr) => ({
      universe: Number($(".u-num", tr).value),
      channels: Number($(".u-ch", tr).value),
    })),
    image_size: [Number(f.image_w.value), Number(f.image_h.value)],
    distance: Number(f.distance.value),
    fov: [Number(f.fov_h.value), Number(f.fov_v.value)],
    on_color: [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)),
    settle_ms: Number(f.settle_ms.value),
  };
}

function renderSummary() {
  const st = state.status;
  const rows = st.cams.map((c) => {
    const d = c.detections;
    return `<tr><td>Camera ${c.cam}</td>
      <td>${c.meta.aligned_at ? "saved " + c.meta.aligned_at : "<span class='warn'>not saved</span>"}</td>
      <td>${c.polygon ? c.polygon.length + " points" : "none"}</td>
      <td>${c.captured} / ${st.total_pixels}${c.meta.capture_complete ? "" : c.captured ? " <span class='warn'>(incomplete)</span>" : ""}</td>
      <td>${d ? `${d.located} located, ${d.ambiguous} ambiguous, ${d.none} not found, ${d.hidden} hidden` : "not run"}</td></tr>`;
  }).join("");
  const ref = st.settings.reference_start;
  $("#propSummary").innerHTML = `
    <p>${st.total_pixels} pixels across ${st.layout.length} universe(s).
      Height reference: ${ref === null ? "not locked" : `pixels ${ref}-${ref + st.settings.reference_count - 1}`}.
      Model: ${st.has_model ? "built" : "not built"}.</p>
    <table class="summary-table"><thead><tr><th></th><th>Align</th><th>Mask</th><th>Captured</th><th>Detection</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="hint">Projects folder: <code>${escapeHtml(state.info.projects_root)}</code></p>`;
}

// ----------------------------------------------------------------------------- lights tab

function enterLights() {
  const max = Math.max(0, totalPixels() - 1);
  $("#lightsPixelSlider").max = max;
  $("#lightsPixel").max = max;
}

async function lightsCall(body) {
  const r = await api("POST", propUrl("/lights"), body);
  const text = `Lights: ${r.state}` + (r.error ? ` (send error: ${r.error})` : "");
  $("#lightsState").textContent = text;
  return r;
}

// ----------------------------------------------------------------------------- align tab

function enterAlign() {
  const [w] = frameSize();
  const slider = $("#spreadSlider");
  slider.max = Math.floor(w / 2 - 5);
  const guides = camStatus().meta.guides;
  state.align.spread = guides ? (guides.right_x - guides.left_x) / 2 : Math.round(w / 3);
  slider.value = state.align.spread;
  const s = settings();
  $("#refCount").value = String(s.reference_count);
  const refSlider = $("#refSlider");
  refSlider.max = Math.max(0, totalPixels() - Number($("#refCount").value));
  if (s.reference_start !== null) refSlider.value = s.reference_start;
  updateRefLabel();
  renderAlignSaved();
  drawAlign();
}

function drawAlign() {
  const c = $("#alignCanvas");
  const [w, h] = frameSize();
  c.width = w;
  c.height = h;
  const g = c.getContext("2d");
  g.clearRect(0, 0, w, h);
  const lw = Math.max(2, w / 600);
  line(g, w / 2, 0, w / 2, h, "rgba(79,156,255,.8)", lw);
  line(g, 0, h / 2, w, h / 2, "rgba(79,156,255,.95)", lw);
  const s = state.align.spread || w / 3;
  line(g, w / 2 - s, 0, w / 2 - s, h, "#ffd400", lw * 1.5);
  line(g, w / 2 + s, 0, w / 2 + s, h, "#ffd400", lw * 1.5);
  $("#spreadValue").textContent = `${Math.round(w / 2 - s)} / ${Math.round(w / 2 + s)} px`;
}

function updateRefLabel() {
  const start = Number($("#refSlider").value);
  const count = Number($("#refCount").value);
  const end = Math.min(start + count, totalPixels()) - 1;
  $("#refLabel").textContent = `pixels ${start}-${end}`;
  const s = settings();
  $("#refLocked").textContent = s.reference_start === null
    ? "Not locked yet."
    : `Locked: pixels ${s.reference_start}-${s.reference_start + s.reference_count - 1} (${pixelLocation(s.reference_start)}).`;
}

const sendReference = debounce(() => {
  lightsCall({ action: "range", start: Number($("#refSlider").value), count: Number($("#refCount").value) })
    .catch((e) => toast(e.message, true));
}, 120);

function renderAlignSaved() {
  $("#alignSaved").innerHTML = state.status.cams.map((c) => {
    const m = c.meta;
    if (!m.guides) return `<div>Camera ${c.cam}: not saved</div>`;
    return `<div>Camera ${c.cam}: guides ${Math.round(m.guides.left_x)} / ${Math.round(m.guides.right_x)} px` +
      (m.reference ? `, reference ${m.reference[0]}-${m.reference[0] + m.reference[1] - 1}` : "") + `</div>`;
  }).join("") + (state.status.cams.length === 3
    ? `<p>Go around the prop counter-clockwise seen from above: camera 2 is to the right of camera 1 as you face the prop.</p>` : "");
}

// ----------------------------------------------------------------------------- capture tab

function enterCapture() {
  if (!state.mask.dirty) state.mask.points = (camStatus().polygon || []).map((p) => [...p]);
  renderCaptureInfo();
  drawMask();
}

function drawMask() {
  const c = $("#maskCanvas");
  const [w, h] = frameSize();
  c.width = w;
  c.height = h;
  const g = c.getContext("2d");
  g.clearRect(0, 0, w, h);
  const pts = state.mask.points;
  if (!pts.length) return;
  const lw = Math.max(2, w / 600);
  g.beginPath();
  g.moveTo(pts[0][0], pts[0][1]);
  pts.slice(1).forEach((p) => g.lineTo(p[0], p[1]));
  if (pts.length >= 3) {
    g.closePath();
    g.fillStyle = "rgba(79,156,255,.12)";
    g.fill();
  }
  g.strokeStyle = state.mask.dirty ? "#ffd400" : "#4f9cff";
  g.lineWidth = lw;
  g.stroke();
  g.fillStyle = "#fff";
  pts.forEach((p) => { g.beginPath(); g.arc(p[0], p[1], lw * 2, 0, Math.PI * 2); g.fill(); });
}

function renderCaptureInfo() {
  const c = camStatus();
  const total = totalPixels();
  const n = state.mask.points.length;
  $("#maskInfo").textContent = state.mask.dirty
    ? `${n} points, not saved yet.`
    : c.polygon ? `Saved mask with ${c.polygon.length} points.` : "No mask yet; detection will use the whole frame.";
  const m = c.meta;
  let text = `${c.captured} of ${total} pixels captured for camera ${state.cam}.`;
  if (m.capture_started) text += ` Started ${m.capture_started}.`;
  if (m.capture_complete) text += " Complete.";
  if (m.exposure_locked === false) text += " Exposure lock was not accepted by this camera; if detection struggles, use the neighboring-frames background.";
  $("#captureInfo").textContent = text;
  const running = state.job && state.job.state === "running";
  $("#captureStartBtn").disabled = running;
  $("#captureResumeBtn").disabled = running || c.captured === 0 || c.captured >= total;
}

async function startCapture(resume) {
  if (!state.camera || !state.camera.open) throw new Error("Open the camera first (Project tab).");
  const c = camStatus();
  if (!resume && c.captured > 0 && !confirm(`Replace the ${c.captured} frames already captured for camera ${state.cam}?`)) return;
  if (state.mask.dirty && !confirm("The mask has unsaved changes. Start anyway?")) return;
  const job = await api("POST", camUrl("/capture"), { resume });
  handleJob(job);
}

// ----------------------------------------------------------------------------- review tab

const reviewFilters = {
  attention: (it) => it.captured && (it.status === "none" || it.status === "ambiguous"),
  all: () => true,
  ambiguous: (it) => it.status === "ambiguous",
  none: (it) => it.status === "none",
  manual: (it) => it.status === "manual",
  hidden: (it) => it.status === "hidden",
};

async function loadDetections() {
  const data = await api("GET", camUrl("/detections"));
  const r = state.review;
  r.items = data.items;
  r.total = data.total;
  r.detected = data.detected;
  r.polygon = data.polygon;
  r.meta = data.meta;
  renderDetSummary();
  if (data.meta.exposure_locked === false) $("#detBackground").value = "neighbors";
  renderStrip();
  if (r.index >= r.total) r.index = 0;
  const filter = reviewFilters[$("#reviewFilter").value];
  if (!filter(r.items[r.index] || {})) {
    const first = r.items.find(filter);
    if (first) r.index = first.index;
  }
  showPixel(r.index);
}

function stripClass(it) {
  if (!it.captured) return "uncaptured";
  return it.status === "hidden" ? "hidden-s" : it.status;
}

function renderStrip() {
  const strip = $("#pixelStrip");
  strip.innerHTML = "";
  const frag = document.createDocumentFragment();
  state.review.items.forEach((it) => {
    const span = document.createElement("span");
    span.className = stripClass(it);
    span.title = `#${it.index} ${it.status}`;
    span.dataset.index = it.index;
    frag.appendChild(span);
  });
  strip.appendChild(frag);
}

function updateStripCell(it) {
  const span = $(`#pixelStrip span[data-index="${it.index}"]`);
  if (span) {
    span.className = stripClass(it) + (it.index === state.review.index ? " current" : "");
    span.title = `#${it.index} ${it.status}`;
  }
}

function showPixel(index) {
  const r = state.review;
  if (!r.items.length) return;
  index = Math.max(0, Math.min(index, r.total - 1));
  const prev = $("#pixelStrip span.current");
  if (prev) prev.classList.remove("current");
  r.index = index;
  const cell = $(`#pixelStrip span[data-index="${index}"]`);
  if (cell) cell.classList.add("current");
  $("#reviewIndex").value = index;
  const it = r.items[index];
  $("#reviewTitle").textContent = `Pixel ${index}`;
  $("#reviewInfo").innerHTML = `${escapeHtml(pixelLocation(index))}<br>` +
    `status: ${it.status}` + (it.x !== null ? `, at ${it.x.toFixed(1)}, ${it.y.toFixed(1)}` : "") +
    (it.status === "ok" || it.status === "ambiguous" ? `, confidence ${it.confidence.toFixed(2)}` : "") +
    (it.captured ? "" : "<br><span class='warn'>frame not captured</span>");
  const img = $("#reviewImg");
  if (!it.captured) {
    img.removeAttribute("src");
    drawReview();
    return;
  }
  const diff = $("#diffToggle").checked;
  img.src = camUrl(`/image/${index}`) + (diff ? `?diff=1&background=${$("#detBackground").value}` : "");
}

function layoutReview() {
  const img = $("#reviewImg");
  const canvas = $("#reviewCanvas");
  if (!img.naturalWidth) return;
  const zoom = Number($("#zoomSelect").value);
  const scroll = $("#reviewScroll");
  const width = zoom === 0 ? scroll.clientWidth : img.naturalWidth * zoom;
  img.style.width = `${width}px`;
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${(width / img.naturalWidth) * img.naturalHeight}px`;
  drawReview();
  if (zoom > 0) {
    const it = state.review.items[state.review.index];
    let cx, cy;
    if (it && it.x !== null) { cx = it.x; cy = it.y; }
    else if (state.review.polygon) {
      cx = state.review.polygon.reduce((a, p) => a + p[0], 0) / state.review.polygon.length;
      cy = state.review.polygon.reduce((a, p) => a + p[1], 0) / state.review.polygon.length;
    }
    if (cx !== undefined) {
      const s = width / img.naturalWidth;
      scroll.scrollLeft = cx * s - scroll.clientWidth / 2;
      scroll.scrollTop = cy * s - scroll.clientHeight / 2;
    }
  }
}

function drawReview() {
  const canvas = $("#reviewCanvas");
  const g = canvas.getContext("2d");
  g.clearRect(0, 0, canvas.width, canvas.height);
  const r = state.review;
  const lw = Math.max(2, canvas.width / 700);
  if (r.polygon) {
    g.beginPath();
    g.moveTo(r.polygon[0][0], r.polygon[0][1]);
    r.polygon.slice(1).forEach((p) => g.lineTo(p[0], p[1]));
    g.closePath();
    g.strokeStyle = "rgba(79,156,255,.5)";
    g.lineWidth = lw;
    g.stroke();
  }
  const it = r.items[r.index];
  if (it && it.x !== null) {
    const color = { ok: "#3fb950", manual: "#4f9cff", ambiguous: "#d29922" }[it.status] || "#fff";
    g.strokeStyle = color;
    g.lineWidth = lw;
    g.beginPath();
    g.arc(it.x, it.y, lw * 8, 0, Math.PI * 2);
    g.stroke();
    line(g, it.x - lw * 14, it.y, it.x - lw * 9, it.y, color, lw);
    line(g, it.x + lw * 9, it.y, it.x + lw * 14, it.y, color, lw);
    line(g, it.x, it.y - lw * 14, it.x, it.y - lw * 9, color, lw);
    line(g, it.x, it.y + lw * 9, it.x, it.y + lw * 14, color, lw);
  }
}

function renderDetSummary() {
  const r = state.review;
  if (!r.detected) {
    $("#detSummary").textContent = `Camera ${state.cam}: detection has not been run. ${r.items.filter((i) => i.captured).length} frames captured.`;
    return;
  }
  const n = { ok: 0, manual: 0, ambiguous: 0, none: 0, hidden: 0 };
  r.items.forEach((it) => { n[it.status] = (n[it.status] || 0) + 1; });
  $("#detSummary").textContent =
    `Camera ${state.cam}: ${n.ok} found, ${n.manual} manual, ${n.ambiguous} ambiguous, ${n.none} not found, ${n.hidden} hidden (of ${r.total}).`;
}

async function setDetection(body, advance = true) {
  const r = state.review;
  const updated = await api("PUT", camUrl(`/detections/${r.index}`), body);
  const it = r.items[r.index];
  Object.assign(it, updated);
  updateStripCell(it);
  renderDetSummary();
  if (advance && $("#reviewFilter").value !== "all") stepPixel(1, true);
  else showPixel(r.index);
}

function stepPixel(dir, quiet = false) {
  const r = state.review;
  const filter = reviewFilters[$("#reviewFilter").value];
  for (let i = r.index + dir; i >= 0 && i < r.total; i += dir) {
    if (filter(r.items[i])) return showPixel(i);
  }
  if (!quiet) toast("No more pixels in this list.");
  showPixel(r.index);
}

// ----------------------------------------------------------------------------- model tab

async function enterModel() {
  const f = $("#modelForm");
  const m = settings().model;
  f.fill_short_gaps_only.checked = m.fill_short_gaps_only;
  f.max_gap.value = m.max_gap;
  f.max_gap.disabled = !m.fill_short_gaps_only;
  f.grid_cells.value = m.grid_cells || "";
  f.scale_factor.value = m.scale_factor || "";
  f.sizing.value = m.scale_factor ? "scale" : "cells";
  updateSizing();
  f.min_ray_angle.value = m.min_ray_angle;
  f.outlier_fraction.value = m.outlier_fraction;
  f.use_ambiguous.checked = m.use_ambiguous;
  const result = await api("GET", propUrl("/model"));
  renderModel(result);
  renderCamPlots().catch((e) => toast(e.message, true));
}

function updateSizing() {
  const byScale = $("#modelForm").sizing.value === "scale";
  $(".sizing-scale").classList.toggle("hidden", !byScale);
  $(".sizing-cells").classList.toggle("hidden", byScale);
}

function readModelForm() {
  const f = $("#modelForm");
  const byScale = f.sizing.value === "scale";
  if (byScale && !(Number(f.scale_factor.value) > 0)) throw new Error("Enter a scale factor greater than 0.");
  return {
    fill_short_gaps_only: f.fill_short_gaps_only.checked,
    max_gap: Number(f.max_gap.value) || 5,
    grid_cells: f.grid_cells.value ? Number(f.grid_cells.value) : null,
    scale_factor: byScale ? Number(f.scale_factor.value) : null,
    min_ray_angle: Number(f.min_ray_angle.value),
    outlier_fraction: Number(f.outlier_fraction.value),
    use_ambiguous: f.use_ambiguous.checked,
  };
}

function renderModel(result) {
  const el = $("#modelSummary");
  $("#modelDownloads").classList.toggle("hidden", !result);
  if (!result) {
    el.innerHTML = `<p class="hint">Not built yet.</p>`;
    $("#finalPlot").innerHTML = "";
    return;
  }
  $$("#modelDownloads a").forEach((a) => {
    a.href = propUrl(`/model/download/${a.dataset.kind}`) + `?t=${Date.now()}`;
  });
  const runs = result.empty_runs.map(([s, e]) => (s === e ? `${s}` : `${s}-${e} (${e - s + 1})`));
  const st = result.stats || {};
  const g = result.grid;
  el.innerHTML = `
    <table class="summary-table">
      <tr><th>Built</th><td>${result.built}</td></tr>
      <tr><th>Pixels</th><td>${result.measured} measured, ${result.filled} filled, ${result.missing} left empty (of ${result.total})</td></tr>
      ${runs.length ? `<tr><th>Empty runs</th><td class="mono">${runs.join(", ")}</td></tr>` : ""}
      <tr><th>xLights grid</th><td>${g.cols} wide x ${g.rows} high${result.mode === "3d" ? ` x ${g.layers} deep` : ""};
        ${g.units_per_cell !== undefined ? `scale factor ${g.units_per_cell} (${escapeHtml(g.sized_by)});` : ""}
        ${g.nudged} pixel(s) moved to a free cell${g.nodes !== undefined ? `; ${g.nodes} nodes in the .xmodel` : ""}</td></tr>
      ${result.mode === "3d" ? `<tr><th>Camera pairs</th><td>${st.grazing_or_behind} rejected (rays too close to parallel or behind a camera),
        ${st.outlier_dropped} outlier pair(s) dropped, ${st.disagree} pixel(s) where pairs disagreed, ${st.single_pair} from a single pair</td></tr>` : ""}
    </table>
    ${result.warnings.map((w) => `<p class="warn">${escapeHtml(w)}</p>`).join("")}`;
  plotFinal(result).catch((e) => { $("#finalPlot").innerHTML = `<p class="warn">${escapeHtml(e.message)}</p>`; });
}

let plotlyPromise = null;
function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!plotlyPromise) {
    plotlyPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = PLOTLY_URL;
      s.onload = () => resolve(window.Plotly);
      s.onerror = () => {
        plotlyPromise = null;
        reject(new Error("Plots need an internet connection to load Plotly. Downloads still work."));
      };
      document.head.appendChild(s);
    });
  }
  return plotlyPromise;
}

const darkLayout = (extra) => ({
  paper_bgcolor: "#1b2029",
  plot_bgcolor: "#1b2029",
  font: { color: "#e6e9ef", size: 12 },
  margin: { l: 40, r: 10, t: 30, b: 35 },
  showlegend: true,
  legend: { orientation: "h", y: -0.08 },
  ...extra,
});

async function plotFinal(result) {
  const Plotly = await loadPlotly();
  const pts = result.points;
  const is3d = result.mode === "3d";
  const measured = [], filled = [];
  pts.forEach((p, i) => {
    if (p[0] === null) return;
    (result.notes[i] === "filled" ? filled : measured).push(i);
  });
  const axis = (idx, k) => idx.map((i) => pts[i][k]);
  const text = (idx) => idx.map((i) => `pixel ${i} (${result.notes[i]})`);
  const path = {
    name: "string order",
    x: pts.map((p) => p[0]), y: pts.map((p) => p[1]),
    mode: "lines", line: { color: "rgba(160,170,190,.35)", width: 1 }, hoverinfo: "skip",
    connectgaps: false,
  };
  const marker = (idx, symbol, size) => ({
    color: idx, colorscale: "Viridis", cmin: 0, cmax: result.total - 1, size, symbol,
  });
  const mTrace = {
    name: "measured", x: axis(measured, 0), y: axis(measured, 1), text: text(measured), hoverinfo: "text",
    mode: "markers", marker: { ...marker(measured, "circle", is3d ? 3 : 6), colorbar: { title: "pixel", thickness: 12 } },
  };
  const fTrace = {
    name: "filled", x: axis(filled, 0), y: axis(filled, 1), text: text(filled), hoverinfo: "text",
    mode: "markers", marker: marker(filled, is3d ? "diamond-open" : "diamond-open", is3d ? 4 : 8),
  };
  if (is3d) {
    for (const t of [path, mTrace, fTrace]) t.type = "scatter3d";
    path.z = pts.map((p) => p[2]);
    mTrace.z = axis(measured, 2);
    fTrace.z = axis(filled, 2);
    await Plotly.react("finalPlot", [path, mTrace, fTrace], darkLayout({
      scene: {
        aspectmode: "data",
        xaxis: { title: "X", color: "#9aa3b2" }, yaxis: { title: "Y", color: "#9aa3b2" }, zaxis: { title: "Z (up)", color: "#9aa3b2" },
        bgcolor: "#1b2029",
      },
      margin: { l: 0, r: 0, t: 10, b: 0 },
    }), { responsive: true });
  } else {
    for (const t of [path, mTrace, fTrace]) t.type = "scattergl";
    await Plotly.react("finalPlot", [path, mTrace, fTrace], darkLayout({
      xaxis: { title: "X", gridcolor: "#2c3340" },
      yaxis: { title: "Y (up)", gridcolor: "#2c3340", scaleanchor: "x" },
    }), { responsive: true });
  }
}

async function renderCamPlots() {
  const container = $("#camPlots");
  const n = state.status.cams.length;
  container.innerHTML = Array.from({ length: n }, (_, i) => `<div id="camPlot${i + 1}"></div>`).join("");
  let Plotly;
  try { Plotly = await loadPlotly(); } catch (e) {
    container.innerHTML = `<p class="warn">${escapeHtml(e.message)}</p>`;
    return;
  }
  for (let cam = 1; cam <= n; cam++) {
    const data = await api("GET", propUrl(`/cams/${cam}/detections`));
    const div = `camPlot${cam}`;
    if (!data.detected) {
      $(`#${div}`).innerHTML = `<p class="hint">Camera ${cam}: detection not run.</p>`;
      continue;
    }
    const size = data.meta.image_size || state.status.settings.image_size;
    const good = data.items.filter((it) => it.x !== null && (it.status === "ok" || it.status === "manual"));
    const amb = data.items.filter((it) => it.x !== null && it.status === "ambiguous");
    const s = data.summary;
    await Plotly.react(div, [
      {
        type: "scattergl", name: "found / manual", mode: "markers",
        x: good.map((it) => it.x), y: good.map((it) => it.y), text: good.map((it) => `pixel ${it.index} (${it.status})`),
        hoverinfo: "text", marker: { color: good.map((it) => it.index), colorscale: "Viridis", cmin: 0, cmax: data.total - 1, size: 5 },
      },
      {
        type: "scattergl", name: "ambiguous", mode: "markers",
        x: amb.map((it) => it.x), y: amb.map((it) => it.y), text: amb.map((it) => `pixel ${it.index} (ambiguous)`),
        hoverinfo: "text", marker: { color: "#d29922", symbol: "x", size: 7 },
      },
    ], darkLayout({
      title: { text: `Camera ${cam}: ${s.located} of ${s.total} located, ${s.none + s.hidden} missing`, font: { size: 13 } },
      xaxis: { range: [0, size[0]], gridcolor: "#2c3340", constrain: "domain" },
      yaxis: { range: [size[1], 0], gridcolor: "#2c3340", scaleanchor: "x" },
    }), { responsive: true });
  }
}

// ----------------------------------------------------------------------------- jobs

async function pollJob() {
  try {
    handleJob(await api("GET", "/api/job"));
  } catch { /* server restarting */ }
  setTimeout(pollJob, state.job && state.job.state === "running" ? 1000 : 4000);
}

function handleJob(job) {
  const prev = state.job;
  state.job = job;
  const bar = $("#jobBar");
  const recent = job && (job.state === "running" || Date.now() / 1000 - (job.finished || 0) < 20);
  bar.classList.toggle("hidden", !recent);
  if (job) {
    $("#jobLabel").textContent = job.label;
    $("#jobProgress").max = job.total || 1;
    $("#jobProgress").value = job.progress;
    $("#jobMessage").textContent = job.state === "error" ? job.error : job.state === "running" ? job.message : `${job.state}: ${job.message}`;
    $("#jobCancelBtn").classList.toggle("hidden", job.state !== "running");
  }
  const finished = prev && prev.state === "running" && job && job.id === prev.id && job.state !== "running";
  if (finished) {
    toast(job.state === "error" ? job.error : `${job.label}: ${job.state}`, job.state === "error");
    refreshStatus().then(() => {
      renderProject();
      if (state.tab === "review" && job.kind === "detect") loadDetections();
      else if (state.tab === "capture") renderCaptureInfo();
    }).catch(() => {});
  } else if (job && job.state === "running" && job.kind === "capture" && state.tab === "capture" && state.status) {
    const c = camStatus();
    if (c) {
      c.captured = job.progress;
      renderCaptureInfo();
    }
  }
}

// ----------------------------------------------------------------------------- wiring

function bindUI() {
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  on("#projectSelect", "change", async (e) => { state.project = e.target.value; await loadProject(); });
  on("#propSelect", "change", async (e) => { state.prop = e.target.value; state.mask.dirty = false; await loadProp(); });

  on("#newProjectBtn", "click", async () => {
    const r = await promptName("New project (for example the year)");
    if (!r) return;
    await api("POST", "/api/projects", { name: r.name });
    state.project = r.name;
    state.prop = null;
    await loadProjects();
  });

  on("#newPropBtn", "click", async () => {
    if (!state.project) throw new Error("Create a project first.");
    const r = await promptName("New prop (for example tree or bush1)",
      `<label>Mode<select name="mode"><option value="3d">3D, three camera spots</option><option value="2d">2D, one camera spot</option></select></label>`);
    if (!r) return;
    await api("PUT", `/api/projects/${enc(state.project)}/props/${enc(r.name)}`, { mode: r.mode });
    state.prop = r.name;
    await loadProject();
    showTab("project");
  });

  on("#propForm", "submit", async (e) => {
    e.preventDefault();
    await api("PUT", propUrl(), readPropForm());
    toast("Settings saved");
    await loadProp();
  });
  $("#propForm").mode.addEventListener("change", (e) => document.body.classList.toggle("mode-2d", e.target.value === "2d"));
  $("#addUniverseBtn").addEventListener("click", () => {
    const rows = $$("#universeRows tr");
    const last = rows.length ? Number($(".u-num", rows[rows.length - 1]).value) : 1999;
    addUniverseRow(last + 1, 510);
    updatePixelTotal();
  });
  on("#deletePropBtn", "click", async () => {
    if (!confirm(`Remove prop '${state.prop}' from the project? Its folder and images stay on disk.`)) return;
    await api("DELETE", propUrl());
    state.prop = null;
    await loadProject();
  });

  on("#cameraOpenBtn", "click", openCamera);
  $$(".open-camera").forEach((b) => on(b, "click", openCamera));
  on("#cameraCloseBtn", "click", async () => { await api("POST", "/api/camera/close"); await refreshCamera(); });
  on("#cameraProbeBtn", "click", async () => {
    toast("Scanning...");
    const found = await api("GET", "/api/camera/probe");
    toast(found.length ? `USB cameras found at index ${found.join(", ")}` : "No USB cameras found.");
    if (found.length) $("#cameraSource").value = String(found[0]);
  });

  // lights
  on("#lightsOnBtn", "click", () => lightsCall({ action: "on" }));
  on("#lightsOffBtn", "click", () => lightsCall({ action: "off" }));
  on("#lightsPixelBtn", "click", () => lightsCall({ action: "pixel", start: Number($("#lightsPixel").value) }));
  const sendPixel = debounce(() => lightsCall({ action: "pixel", start: Number($("#lightsPixel").value) }).catch((e) => toast(e.message, true)), 120);
  $("#lightsPixelSlider").addEventListener("input", (e) => { $("#lightsPixel").value = e.target.value; sendPixel(); });
  $("#lightsPixel").addEventListener("change", (e) => { $("#lightsPixelSlider").value = e.target.value; sendPixel(); });

  // align
  $("#spreadSlider").addEventListener("input", (e) => { state.align.spread = Number(e.target.value); drawAlign(); });
  $("#refSlider").addEventListener("input", () => { updateRefLabel(); sendReference(); });
  $("#refCount").addEventListener("change", () => {
    $("#refSlider").max = Math.max(0, totalPixels() - Number($("#refCount").value));
    updateRefLabel();
    sendReference();
  });
  const stepRef = (d) => {
    const s = $("#refSlider");
    s.value = Math.max(0, Math.min(Number(s.max), Number(s.value) + d));
    updateRefLabel();
    sendReference();
  };
  $("#refStepDown").addEventListener("click", () => stepRef(-1));
  $("#refStepUp").addEventListener("click", () => stepRef(1));
  on("#refLockBtn", "click", async () => {
    await api("POST", propUrl("/reference"), { start: Number($("#refSlider").value), count: Number($("#refCount").value) });
    await refreshStatus();
    updateRefLabel();
    toast("Reference locked; other camera spots will light the same pixels.");
  });
  on("#refUnlockBtn", "click", async () => {
    await api("POST", propUrl("/reference"), { start: null });
    await refreshStatus();
    updateRefLabel();
  });
  on("#refShowBtn", "click", async () => {
    const s = settings();
    if (s.reference_start === null) throw new Error("No reference locked yet.");
    $("#refSlider").value = s.reference_start;
    $("#refCount").value = String(s.reference_count);
    updateRefLabel();
    await lightsCall({ action: "range", start: s.reference_start, count: s.reference_count });
  });
  on("#refOffBtn", "click", () => lightsCall({ action: "off" }));
  on("#saveAlignBtn", "click", async () => {
    const [w] = frameSize();
    const spread = state.align.spread;
    await api("PUT", camUrl("/align"), { left_x: w / 2 - spread, right_x: w / 2 + spread });
    await refreshStatus();
    renderAlignSaved();
    toast(`Camera spot ${state.cam} saved`);
  });

  // capture
  on("#maskCanvas", "click", (e) => {
    state.mask.points.push(canvasPoint($("#maskCanvas"), e).map(Math.round));
    state.mask.dirty = true;
    drawMask();
    renderCaptureInfo();
  });
  on("#maskUndoBtn", "click", () => { state.mask.points.pop(); state.mask.dirty = true; drawMask(); renderCaptureInfo(); });
  on("#maskClearBtn", "click", () => { state.mask.points = []; state.mask.dirty = true; drawMask(); renderCaptureInfo(); });
  on("#maskSaveBtn", "click", async () => {
    await api("PUT", camUrl("/polygon"), { points: state.mask.points });
    state.mask.dirty = false;
    await refreshStatus();
    renderCaptureInfo();
    drawMask();
    toast("Mask saved");
  });
  on("#maskLightsOnBtn", "click", () => lightsCall({ action: "on" }));
  on("#maskLightsOffBtn", "click", () => lightsCall({ action: "off" }));
  on("#captureStartBtn", "click", () => startCapture(false));
  on("#captureResumeBtn", "click", () => startCapture(true));
  on("#jobCancelBtn", "click", () => api("POST", "/api/job/cancel"));

  // review
  on("#detectBtn", "click", async () => {
    const job = await api("POST", camUrl("/detect"), {
      background: $("#detBackground").value,
      min_peak: Number($("#detMinPeak").value),
      keep_manual: $("#detKeepManual").checked,
    });
    handleJob(job);
  });
  $("#pixelStrip").addEventListener("click", (e) => {
    if (e.target.dataset.index !== undefined) showPixel(Number(e.target.dataset.index));
  });
  $("#reviewImg").addEventListener("load", layoutReview);
  $("#reviewImg").addEventListener("error", () => drawReview());
  $("#zoomSelect").addEventListener("change", layoutReview);
  $("#diffToggle").addEventListener("change", () => showPixel(state.review.index));
  $("#reviewFilter").addEventListener("change", () => stepPixel(1));
  $("#prevBtn").addEventListener("click", () => stepPixel(-1));
  $("#nextBtn").addEventListener("click", () => stepPixel(1));
  $("#reviewIndex").addEventListener("change", (e) => showPixel(Number(e.target.value)));
  on("#reviewCanvas", "click", async (e) => {
    const it = state.review.items[state.review.index];
    if (!it || !it.captured) return;
    const [x, y] = canvasPoint($("#reviewCanvas"), e);
    await setDetection({ status: "manual", x, y });
  });
  on("#acceptBtn", "click", () => setDetection({ status: "ok" }));
  on("#hiddenBtn", "click", () => setDetection({ status: "hidden" }));
  on("#clearBtn", "click", () => setDetection({ status: "none" }, false));
  document.addEventListener("keydown", (e) => {
    if (state.tab !== "review" || e.target.matches("input, select, textarea")) return;
    const key = e.key.toLowerCase();
    const run = (p) => p.catch((err) => toast(err.message, true));
    if (key === "arrowright") { stepPixel(1); e.preventDefault(); }
    else if (key === "arrowleft") { stepPixel(-1); e.preventDefault(); }
    else if (key === "a") run(setDetection({ status: "ok" }));
    else if (key === "h") run(setDetection({ status: "hidden" }));
    else if (key === "c") run(setDetection({ status: "none" }, false));
    else if (key === "d") { $("#diffToggle").checked = !$("#diffToggle").checked; showPixel(state.review.index); }
  });
  window.addEventListener("resize", debounce(() => { if (state.tab === "review") layoutReview(); }, 150));

  // model
  $("#modelForm").fill_short_gaps_only.addEventListener("change", (e) => { $("#modelForm").max_gap.disabled = !e.target.checked; });
  $("#modelForm").sizing.addEventListener("change", updateSizing);
  on("#modelForm", "submit", async (e) => {
    e.preventDefault();
    toast("Building model...");
    const result = await api("POST", propUrl("/model"), readModelForm());
    await refreshStatus();
    renderModel(result);
    renderCamPlots().catch((err) => toast(err.message, true));
    toast("Model built");
  });
}

async function init() {
  state.info = await api("GET", "/api/info");
  $("#rootPath").textContent = state.info.projects_root;
  $("#cameraSource").value = state.info.settings.camera_source ?? "0";
  bindUI();
  await refreshCamera();
  await loadProjects();
  showTab(state.tab);
  pollJob();
}

init().catch((err) => toast(err.message, true));
