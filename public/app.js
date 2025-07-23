let timerState = {
  status: "idle",
  timeRemaining: 0,
  lastUpdated: Date.now(),
  message: ""
};

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
  }
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

  timer.className = "";
  let showTimer = false;

  if (["pre_draw", "running", "complete"].includes(timerState.status)) {
    showTimer = true;
    document.body.classList.add("running");
    if (timerState.timeRemaining < 300) {
      document.body.classList.add("warning");
    }else{
      document.body.classList.remove("warning");
    }
    if (timerState.timeRemaining <= 0) {
      document.body.classList.add("critical");
    }else{
      document.body.classList.remove("critical");
    }
    timer.innerHTML = formatTime(Math.max(timerState.timeRemaining, 0));
  } else {
    timer.innerHTML = "";
    document.body.classList.remove("running");
    document.body.classList.remove("warning");
    document.body.classList.remove("critical");
  }

  // Adjust font size of label based on timer visibility
  document.body.classList.toggle("no-timer", !showTimer);
}

function tick() {
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

    render();
  } catch (e) {
    console.error("Timer sync failed", e);
  }
}

setInterval(tick, 1000);
setInterval(syncState, 5000);
syncState();
