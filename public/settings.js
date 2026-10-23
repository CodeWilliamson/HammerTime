const STATES = [
  { key: "", label: "Idle" },
  { key: "running", label: "Running" },
  { key: "warning", label: "Warning" },
  { key: "critical", label: "Game End" },
];
const ELEMENTS = [
  { key: "background", label: "Background" },
  { key: "timer", label: "Timer" },
  { key: "status", label: "Status" },
  { key: "message", label: "Message" },
];
let savedConfig = {};
let baseline = {};

function fieldName(element, state) {
  return `${element}_color${state ? "_" + state : ""}`;
}

function buildColorMatrix() {
  const matrix = document.getElementById("colorMatrix");
  matrix.appendChild(document.createElement("div"));
  ELEMENTS.forEach((el) => {
    const head = document.createElement("div");
    head.className = "matrix-head";
    head.textContent = el.label;
    matrix.appendChild(head);
  });
  STATES.forEach((state) => {
    const rowLabel = document.createElement("div");
    rowLabel.className = "matrix-row-label";
    rowLabel.textContent = state.label;
    matrix.appendChild(rowLabel);
    ELEMENTS.forEach((el) => {
      const cell = document.createElement("div");
      cell.className = "matrix-cell";
      const input = document.createElement("input");
      input.type = "color";
      input.name = fieldName(el.key, state.key);
      input.title = `${el.label} (${state.label})`;
      input.setAttribute("aria-label", input.title);
      cell.appendChild(input);
      matrix.appendChild(cell);
    });
  });
}

// Mirrors formatTime() in app.js so the preview matches the kiosk
function formatTimeParts(seconds, dynamic) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const ss = String(s).padStart(2, "0");

  if (dynamic) {
    if (seconds < 60) return { main: ss, sec: "" };
    if (seconds < 3600) return { main: `${String(m).padStart(2, "0")}:${ss}`, sec: "" };
  }
  return { main: `${h}:${String(m).padStart(2, "0")}`, sec: `:${ss}` };
}

function buildPreview() {
  const grid = document.getElementById("previewGrid");
  // Seconds rather than formatted text, so updatePreview() can re-render the
  // timer when the dynamic format checkbox changes.
  const samples = {
    "": { status: "Next draw: 7:00 PM", seconds: null, message: "Social" },
    running: { status: "Time remaining:", seconds: 45 * 60, message: "Men's House" },
    warning: { status: "Time remaining:", seconds: 45, message: "Women's House" },
    critical: { status: "Time's Up!", seconds: 0, message: "" },
  };
  STATES.forEach((state) => {
    const s = samples[state.key];
    const tile = document.createElement("div");
    tile.className = "preview-tile";
    tile.dataset.state = state.key;
    tile.innerHTML = `
      <span class="preview-tag"></span>
      <div class="p-status"></div>
      <div class="p-timer"></div>
      <div class="p-message"></div>`;
    tile.querySelector(".preview-tag").textContent = state.label;
    tile.querySelector(".p-status").textContent = s.status;
    tile.querySelector(".p-message").textContent = s.message;
    if (s.seconds != null) tile.dataset.seconds = String(s.seconds);
    grid.appendChild(tile);
  });
}

function updatePreview() {
  const form = document.getElementById("configForm");
  const dynamicEnabled = form.dynamic_timer_format.checked;
  document.querySelectorAll(".preview-tile").forEach((tile) => {
    const state = tile.dataset.state;
    const val = (el) => form[fieldName(el, state)].value;
    tile.style.background = val("background");
    tile.querySelector(".p-timer").style.color = val("timer");
    tile.querySelector(".p-status").style.color = val("status");
    tile.querySelector(".p-message").style.color = val("message");

    // The kiosk ignores the dynamic setting for a finished countdown, so "Game End" keeps 0:00:00
    const dynamic = dynamicEnabled && !(state === "critical" && Number(tile.dataset.seconds) === 0);
    const timer = tile.querySelector(".p-timer");
    timer.textContent = "";
    if (tile.dataset.seconds != null) {
      const { main, sec } = formatTimeParts(Number(tile.dataset.seconds), dynamic);
      timer.textContent = main;
      if (sec) {
        const span = document.createElement("span");
        span.className = "p-timer-sec";
        span.textContent = sec;
        timer.appendChild(span);
      }
    }

    // Tile is a size container, so 1cqw here equals 1vw on the kiosk
    const size = (name, fallback) => `${parseFloat(form[name].value) || fallback}cqw`;
    timer.style.fontSize = size("timer_font_size", 28);
    tile.querySelector(".p-status").style.fontSize = size("label_font_size", 5);
    tile.querySelector(".p-message").style.fontSize = size("message_font_size", 5);
  });
}

// Font sizes are stored as "<n>vw"; the slider and stepper both edit the hidden field
function clampSize(control, n) {
  const min = parseFloat(control.dataset.min);
  const max = parseFloat(control.dataset.max);
  return Math.min(max, Math.max(min, n));
}

function syncSizeControl(control) {
  const hidden = control.querySelector('input[type="hidden"]');
  const [range, num] = control.querySelectorAll('input[type="range"], input[type="number"]');
  const parsed = parseFloat(hidden.value);
  const n = clampSize(control, Number.isFinite(parsed) ? parsed : parseFloat(control.dataset.min));
  hidden.value = `${n}vw`;
  range.value = n;
  num.value = n;
}

function setupSizeControls() {
  document.querySelectorAll(".size-control").forEach((control) => {
    const hidden = control.querySelector('input[type="hidden"]');
    const [range, num] = control.querySelectorAll('input[type="range"], input[type="number"]');
    for (const input of [range, num]) {
      input.min = control.dataset.min;
      input.max = control.dataset.max;
      input.step = control.dataset.step;
    }
    range.addEventListener("input", () => {
      hidden.value = `${range.value}vw`;
      num.value = range.value;
    });
    num.addEventListener("input", () => {
      const n = parseFloat(num.value);
      if (!Number.isFinite(n)) return;
      const clamped = clampSize(control, n);
      hidden.value = `${clamped}vw`;
      range.value = clamped;
    });
    num.addEventListener("change", () => syncSizeControl(control));
  });
}

function getFormData() {
  const form = document.getElementById("configForm");
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    data[el.name] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value;
  }
  return data;
}

function isDirty() {
  const data = getFormData();
  return Object.keys(data).some((k) => baseline[k] !== data[k]);
}

function refreshState() {
  const dirty = isDirty();
  document.getElementById("saveBtn").disabled = !dirty;
  document.getElementById("resetBtn").disabled = !dirty;
  if (dirty) setStatus("Unsaved changes", "pending");
  else if (document.getElementById("configStatus").dataset.kind === "pending") setStatus("");
  updatePreview();
}

function setStatus(text, kind = "") {
  const el = document.getElementById("configStatus");
  el.textContent = text;
  el.dataset.kind = kind;
}

function fillForm(config) {
  const form = document.getElementById("configForm");
  for (const k in config) {
    if (!(form[k] instanceof HTMLInputElement)) continue;
    if (form[k].type === "checkbox") form[k].checked = Boolean(config[k]);
    else form[k].value = config[k] ?? "";
  }
  // Snapshot after the browser normalizes values (e.g. color hex casing), before sizes are coerced to vw
  baseline = getFormData();
  document.querySelectorAll(".size-control").forEach(syncSizeControl);
  refreshState();
}

async function loadConfig() {
  const res = await fetch("/api/timer/config", { credentials: "include" });
  if (res.status === 401 || res.status === 403) {
    window.location.href = "/login.html";
    return;
  }
  if (!res.ok) {
    setStatus("Could not load settings.", "error");
    return;
  }
  savedConfig = await res.json();
  fillForm(savedConfig);
}

async function saveConfig(e) {
  e.preventDefault();
  const saveBtn = document.getElementById("saveBtn");
  saveBtn.disabled = true;
  setStatus("Saving…", "pending");
  const res = await fetch("/api/timer/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(getFormData()),
  });
  if (res.status === 401 || res.status === 403) {
    window.location.href = "/login.html";
    return;
  }
  if (res.ok) {
    setStatus("Saved", "success");
    setTimeout(() => {
      if (document.getElementById("configStatus").dataset.kind === "success") setStatus("");
    }, 2000);
    // The server broadcasts the updated config over WS; apply it when it arrives.
    // Fall back to re-fetching if no broadcast arrives within 2 seconds.
    setTimeout(loadConfig, 2000);
  } else {
    setStatus("Error saving settings.", "error");
    saveBtn.disabled = false;
  }
}

window.addEventListener("beforeunload", (e) => {
  if (isDirty()) e.preventDefault();
});

async function loadVersion() {
  try {
    const res = await fetch("/api/version");
    if (!res.ok) return;
    const { version } = await res.json();
    document.getElementById("appVersion").textContent = `Version ${version}`;
  } catch {
    // Version is informational only
  }
}

buildColorMatrix();
buildPreview();
loadVersion();
setupSizeControls();
const form = document.getElementById("configForm");
form.addEventListener("input", refreshState);
form.addEventListener("submit", saveConfig);
document.getElementById("resetBtn").addEventListener("click", () => {
  fillForm(savedConfig);
  setStatus("");
});

// --- Server-Sent Events: receive live config updates from the server ---
// EventSource reconnects automatically on blips; reopen manually only if the
// stream fails permanently (readyState === CLOSED, e.g. a non-2xx response).
let reopenTimer = null;

function connectStream() {
  const es = new EventSource("/events");

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED && !reopenTimer) {
      reopenTimer = setTimeout(() => {
        reopenTimer = null;
        connectStream();
      }, 10000);
    }
  };

  es.addEventListener("config", (event) => {
    try {
      const msg = JSON.parse(event.data);
      // Apply config pushed by the server (e.g. after another admin saved changes)
      fillForm(msg);
      refreshState();
    } catch {
      // ignore malformed messages
    }
  });
}

connectStream();
loadConfig();
