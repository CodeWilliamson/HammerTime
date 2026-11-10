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
// Preview samples. `seconds` is kept numeric so updatePreview() can re-render the
// countdown when the dynamic format checkbox changes.
const PREVIEW_SAMPLES = {
  "": { status: "Next draw: 7:00 PM", seconds: null, message: "Social" },
  running: { status: "Time Remaining", seconds: 45 * 60, message: "Men's House" },
  warning: { status: "Time Remaining", seconds: 28, message: "Women's House" },
  critical: { status: "Time's Up!", seconds: 0, message: "" },
};
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
  STATES.forEach((state) => {
    const s = PREVIEW_SAMPLES[state.key];
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
  // Same fallback as the kiosk: a blank/invalid threshold means 900 s.
  const warningThreshold = parseFloat(form.running_warning_threshold.value) || 900;
  document.querySelectorAll(".preview-tile").forEach((tile) => {
    const state = tile.dataset.state;
    const val = (el) => form[fieldName(el, state)].value;
    tile.style.background = val("background");
    tile.querySelector(".p-timer").style.color = val("timer");
    tile.querySelector(".p-message").style.color = val("message");

    const status = tile.querySelector(".p-status");
    status.style.color = val("status");
    // While a draw is running the kiosk shows an END badge in place of the status text.
    // It needs only the end counter on and a time per end, so the preview shows it even
    // when no shared "minutes per end" override is configured (a draw's own value is
    // enough on the real display). Like currentEnd() in app.js, the badge is hidden once
    // the countdown reaches the running warning threshold, and END 1 is never shown.
    const seconds = tile.dataset.seconds == null ? null : Number(tile.dataset.seconds);
    const showEnd = form.show_end_number.checked && seconds > 0 && seconds >= warningThreshold;
    status.textContent = "";
    if (showEnd) {
      const badge = document.createElement("span");
      badge.className = "p-end-badge";
      badge.textContent = "END 2";
      status.appendChild(badge);
    } else {
      status.textContent = PREVIEW_SAMPLES[state].status;
    }

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
    status.style.fontSize = size("label_font_size", 5);
    tile.querySelector(".p-message").style.fontSize = size("message_font_size", 5);
  });
}

// Slider + stepper pairs both edit a hidden field, which is what the form submits.
// Font sizes are stored as "<n>vw" (data-suffix); percentages as bare whole numbers.
function clampSize(control, n) {
  const min = parseFloat(control.dataset.min);
  const max = parseFloat(control.dataset.max);
  const clamped = Math.min(max, Math.max(min, n));
  // Steps of 1 or more are whole-number fields (the percent sliders); snap like the
  // range input itself does so a typed "50.4" cannot reach the config.
  return parseFloat(control.dataset.step) >= 1 ? Math.round(clamped) : clamped;
}

function storedSize(control, n) {
  return `${n}${control.dataset.suffix || ""}`;
}

function syncSizeControl(control) {
  const hidden = control.querySelector('input[type="hidden"]');
  const [range, num] = control.querySelectorAll('input[type="range"], input[type="number"]');
  const parsed = parseFloat(hidden.value);
  const n = clampSize(control, Number.isFinite(parsed) ? parsed : parseFloat(control.dataset.min));
  hidden.value = storedSize(control, n);
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
      hidden.value = storedSize(control, range.value);
      num.value = range.value;
    });
    num.addEventListener("input", () => {
      const n = parseFloat(num.value);
      if (!Number.isFinite(n)) return;
      const clamped = clampSize(control, n);
      hidden.value = storedSize(control, clamped);
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
  syncEndCounterFields();
  const dirty = isDirty();
  document.getElementById("saveBtn").disabled = !dirty;
  document.getElementById("resetBtn").disabled = !dirty;
  if (dirty) setStatus("Unsaved changes", "pending");
  else if (document.getElementById("configStatus").dataset.kind === "pending") setStatus("");
  updatePreview();
}

// The "enlarged end number" fields and the system-wide time-per-end override only mean
// something with the end counter on, so their rows are hidden (and the inputs disabled)
// while it is unchecked. The shared minutes field follows its own toggle too. Their
// values are still part of the saved config — getFormData() walks form.elements, which
// includes disabled controls — so switching the counter off and on again keeps them.
function syncEndCounterFields() {
  const form = document.getElementById("configForm");
  const enabled = form.show_end_number.checked;
  for (const name of ["end_highlight_percent", "end_highlight_scale", "end_highlight_timer_percent"]) {
    const input = form[name];
    // Percent fields are slider+stepper pairs; the hidden field carries the name, so the
    // visible controls have to be disabled alongside it.
    const control = input.closest(".size-control");
    for (const el of control ? control.querySelectorAll("input") : [input]) {
      el.disabled = !enabled;
    }
    input.closest(".field-row").hidden = !enabled;
  }

  const override = form.use_system_end_minutes;
  override.disabled = !enabled;
  override.closest(".field-row").hidden = !enabled;

  const minutes = form.system_end_minutes;
  const overrideOn = enabled && override.checked;
  minutes.disabled = !overrideOn;
  minutes.required = overrideOn;
  minutes.closest(".field-row").hidden = !overrideOn;
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

  // Required while the override is on; a stray value is still validated so a number
  // typed before toggling it off cannot reach the database.
  const form = e.target;
  const rawMinutes = form.system_end_minutes.value.trim();
  const validMinutes = /^\d+$/.test(rawMinutes) && Number(rawMinutes) >= 1 && Number(rawMinutes) <= 120;
  const overrideOn = form.show_end_number.checked && form.use_system_end_minutes.checked;
  if (rawMinutes === "" ? overrideOn : !validMinutes) {
    setStatus("Minutes per end must be a whole number between 1 and 120.", "error");
    saveBtn.disabled = false;
    form.system_end_minutes.focus();
    return;
  }

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
