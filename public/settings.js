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
// Matches the kiosk display fallback for the default message color
const DEFAULT_MESSAGE_COLOR = "#eeeeee";

let savedConfig = {};
let baseline = {};

function fieldName(element, state) {
  return `${element}_color${state ? "_" + state : ""}`;
}

function hasField(element, state) {
  return !(element === "message" && !state);
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
      if (hasField(el.key, state.key)) {
        const input = document.createElement("input");
        input.type = "color";
        input.name = fieldName(el.key, state.key);
        input.title = `${el.label} (${state.label})`;
        input.setAttribute("aria-label", input.title);
        cell.appendChild(input);
      } else {
        cell.classList.add("empty");
      }
      matrix.appendChild(cell);
    });
  });
}

function buildPreview() {
  const grid = document.getElementById("previewGrid");
  const samples = {
    "": { status: "Next draw: 7:00 PM", timer: "", message: "" },
    running: { status: "Time remaining:", timer: "38:05", message: "Men's House" },
    warning: { status: "Time remaining:", timer: "4:59", message: "Women's House" },
    critical: { status: "Time's Up!", timer: "0:00", message: "" },
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
    tile.querySelector(".p-timer").textContent = s.timer;
    tile.querySelector(".p-message").textContent = s.message;
    grid.appendChild(tile);
  });
}

function updatePreview() {
  const form = document.getElementById("configForm");
  document.querySelectorAll(".preview-tile").forEach((tile) => {
    const state = tile.dataset.state;
    const val = (el) => (hasField(el, state) ? form[fieldName(el, state)].value : DEFAULT_MESSAGE_COLOR);
    tile.style.background = val("background");
    tile.querySelector(".p-timer").style.color = val("timer");
    tile.querySelector(".p-status").style.color = val("status");
    tile.querySelector(".p-message").style.color = val("message");

    // Tile is a size container, so 1cqw here equals 1vw on the kiosk
    const size = (name, fallback) => `${parseFloat(form[name].value) || fallback}cqw`;
    tile.querySelector(".p-timer").style.fontSize = size("timer_font_size", 28);
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
    await loadConfig();
    setStatus("Saved", "success");
    setTimeout(() => {
      if (document.getElementById("configStatus").dataset.kind === "success") setStatus("");
    }, 2000);
  } else {
    setStatus("Error saving settings.", "error");
    saveBtn.disabled = false;
  }
}

window.addEventListener("beforeunload", (e) => {
  if (isDirty()) e.preventDefault();
});

buildColorMatrix();
buildPreview();
setupSizeControls();
const form = document.getElementById("configForm");
form.addEventListener("input", refreshState);
form.addEventListener("submit", saveConfig);
document.getElementById("resetBtn").addEventListener("click", () => {
  fillForm(savedConfig);
  setStatus("");
});
loadConfig();
