let timerState = {
  status: "idle",
  timeRemaining: 0,
  lastUpdated: Date.now(),
  message: "",
  adminUrl: "",
  ipTimeout: null,
  show_admin_url: true,
  isLocal: false
};

const LOCAL_KEY = "localTimer"; // { targetTime (ms), message }
const LOCAL_COMPLETE_MS = 10 * 60 * 1000; // matches the central 'complete' window

function getLocalTimer() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_KEY));
  } catch {
    return null;
  }
}

// Overrides timerState from local storage. Returns false when there is no active local timer.
function applyLocalTimer() {
  const local = getLocalTimer();
  if (local && Date.now() - local.targetTime >= LOCAL_COMPLETE_MS) {
    localStorage.removeItem(LOCAL_KEY);
    timerState.isLocal = false;
    return false;
  }
  timerState.isLocal = !!local;
  if (!local) return false;

  timerState.targetTimestamp = local.targetTime;
  timerState.timeRemaining = Math.floor((local.targetTime - Date.now()) / 1000);
  timerState.status = timerState.timeRemaining > 0 ? "running" : "complete";
  timerState.label = timerState.status === "running" ? "Time remaining:" : "Time's Up!";
  timerState.message = local.message;
  return true;
}

function applyConfig(config) {
  // Set CSS variables for use in app (can be used in main.css or inline)
  const root = document.documentElement;
  for (const k in config) {
    if (
      k.endsWith('_color') ||
      k.endsWith('_running') ||
      k.endsWith('_warning') ||
      k.endsWith('_critical') ||
      k.endsWith('_font_size')
    ) {
      root.style.setProperty(`--${k.replace(/_/g, '-')}`, config[k]);
    }
    // else if k ends with _threshold, set javascript variable with same name for use in app.js
    else if (k.endsWith('_threshold')) {
      window[k] = config[k];
    }
  }
  document.getElementById("ip-display").hidden = config.show_admin_url === 0
  timerState.show_admin_url = config.show_admin_url !== 0
}

function formatTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;

  const hh = h.toString();
  const mm = String(m).padStart(2, '0');
  return `${hh}:${mm}<span class="small-sec">:${String(s).padStart(2, '0')}</span>`;
}

function formatTimeOfDay(date) {
  return date.toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  });
}

function render() {
  const label = document.getElementById("label");
  const timer = document.getElementById("timer");
  const message = document.getElementById("message");

  label.textContent = timerState.label;
  message.textContent = timerState.message || "";
  document.getElementById("local-badge").hidden = !timerState.isLocal;

  timer.className = "";
  let showTimer = false;

  if (["pre_draw", "running", "complete"].includes(timerState.status)) {
    showTimer = true;
    if( timerState.status === "pre_draw" ){
      document.body.classList.add("pre-draw-neutral");
      document.body.classList.remove("running");
    }else{
      document.body.classList.remove("pre-draw-neutral");
      document.body.classList.add("running");
    }
    
    if ((timerState.status === "pre_draw" && timerState.timeRemaining <  (window['pre_draw_warning_threshold'] || 300)) || (timerState.status === "running" && timerState.timeRemaining < (window['running_warning_threshold'] || 900))) {
      document.body.classList.add("warning");
    }else{
      document.body.classList.remove("warning");
    }
    if ((timerState.status === "running" || timerState.status === "complete") && timerState.timeRemaining <= 0) {
      document.body.classList.add("critical");
    }else{
      document.body.classList.remove("critical");
    }
    timer.innerHTML = formatTime(Math.max(timerState.timeRemaining, 0));
  } else {
    timer.innerHTML = "";
    document.body.classList.remove("pre-draw-neutral");
    document.body.classList.remove("running");
    document.body.classList.remove("warning");
    document.body.classList.remove("critical");
  }

  // Adjust font size of label based on timer visibility
  document.body.classList.toggle("no-timer", !showTimer);
}

function tick() {
  if (applyLocalTimer()) {
    render();
    return;
  }
  if (["pre_draw", "running", "complete"].includes(timerState.status)) {
    const now = Date.now();
    timerState.timeRemaining = Math.floor((timerState.targetTimestamp - now) / 1000);
    render();

    if (timerState.timeRemaining <= 0) {
      syncState(); // force refresh
    }
  }
}

let previousStatus = null; // Add this above syncState()
let lastConfigSeenAt = null;
async function syncState() {
  try {
    const params = new URLSearchParams();
    if (lastConfigSeenAt) {
      params.set("lastConfigSeenAt", lastConfigSeenAt.toISOString());
    }

    const res = await fetch(`/api/timer/state?${params.toString()}`);
    const data = await res.json();

    if (data.config) {
      applyConfig(data.config); // your custom styling logic
      lastConfigSeenAt = new Date(data.config.updated_at);
    }

    // Local timer replaces the central state, but config and admin URL still sync
    if (applyLocalTimer()) {
      showAdminUrl(data);
      render();
      return;
    }

    const oldStatus = timerState.status;

    timerState.status = data.status;
    timerState.timeRemaining = data.timeRemaining ?? 0;
    timerState.lastUpdated = Date.now();
    timerState.targetTimestamp = new Date(data.targetTime).getTime();

    // ✅ Clamp to prevent flickering to 'waiting' from pre_draw/running
    if (oldStatus === "pre_draw" && data.status === "waiting" && (new Date(data.nextDrawStart) - Date.now()) <= 2000) {
      console.log("Suppressing flicker to 'waiting'");
      console.log(`${new Date(data.nextDrawStart) - Date.now()}`);
      setTimeout(() => syncState(), 1000);
      return;
    }

    // Detect transition from pre_draw to running
    // if ((oldStatus === "pre_draw" || oldStatus === "waiting") && data.status === "running") {
    //   document.getElementById("firstcall").play().catch(err => {
    //     console.warn("Autoplay failed:", err);
    //   });
    // }

    if (data.status === "waiting") {
      timerState.label = `Next draw: ${formatTimeOfDay(new Date(data.nextDrawStart))}`;
      timerState.message = data.nextDrawMessage || "";
    } else {
      timerState.label = {
        pre_draw: "Draw starts in:",
        running: "Time remaining:",
        complete: "Time's Up!"
      }[data.status] || "No more draws today";

      timerState.message = data.drawMessage || "";
    }

    // admin url
    showAdminUrl(data);

    render();
  } catch (e) {
    console.error("Timer sync failed", e);
  }
}

// function to display admin url
function showAdminUrl(data) {
  document.getElementById("ip-display").textContent = data.adminUrl || "";
  // if ip has changed
  if (timerState.adminUrl !== data.adminUrl) {
    document.getElementById("ip-display").hidden = false;
    if (timerState.ipTimeout) {
      clearTimeout(timerState.ipTimeout);
      timerState.ipTimeout = null;
    }
    timerState.ipTimeout = setTimeout(() => {
      document.getElementById("ip-display").hidden = timerState.show_admin_url === false;
    }, 10000);
  }else if(!timerState.ipTimeout){
    document.getElementById("ip-display").hidden = timerState.show_admin_url === false;
  }
  timerState.adminUrl = data.adminUrl || "";
}

const localDialog = document.getElementById("local-dialog");
const localAsk = document.getElementById("local-ask");
const localForm = document.getElementById("local-form");
const localDuration = document.getElementById("local-duration");
const localMessage = document.getElementById("local-message");
const localDelete = document.getElementById("local-delete");
let deleteTimeout = null;

function openLocalDialog() {
  localDialog.returnValue = "";
  localAsk.hidden = false;
  localForm.hidden = true;
  localForm.reset();
  localDialog.showModal();
}

// Step 2 of the dialog: show the form, pre-filled with the closest central draw's duration
async function showLocalForm() {
  localAsk.hidden = true;
  localForm.hidden = false;
  localDuration.focus();
  try {
    const res = await fetch("/api/timer/closest-draw-duration");
    const { durationMinutes } = await res.json();
    if (durationMinutes && !localDuration.value) localDuration.value = durationMinutes;
  } catch (e) {
    console.error("Duration prefill failed", e);
  }
}

function startLocalTimer() {
  const minutes = Number(localDuration.value);
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify({
      targetTime: Date.now() + minutes * 60000,
      message: localMessage.value.trim()
    }));
  } catch (e) {
    console.error("Could not save local timer", e);
  }
  tick();
}

// Reveals the small delete button briefly so it is not hit by accident
function revealDeleteButton() {
  localDelete.hidden = false;
  clearTimeout(deleteTimeout);
  deleteTimeout = setTimeout(() => { localDelete.hidden = true; }, 5000);
}

document.getElementById("local-yes").addEventListener("click", showLocalForm);
localDialog.addEventListener("close", () => {
  if (localDialog.returnValue === "start") startLocalTimer();
});

localDelete.addEventListener("click", () => {
  if (!confirm("Delete the local timer and return to the main timer?")) return;
  localStorage.removeItem(LOCAL_KEY);
  localDelete.hidden = true;
  syncState();
});

document.body.addEventListener("click", (e) => {
  if (e.target.closest("dialog, #local-delete")) return;
  if (timerState.isLocal) revealDeleteButton();
  else openLocalDialog();
});

function startTimer() {
  setInterval(tick, 1000);
  setInterval(syncState, 5000);
  syncState();
}

startTimer();