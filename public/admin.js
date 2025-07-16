const daysOfWeek = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
let currentDayIndex = new Date().getDay();

async function loadDraws() {
  const res = await fetch("/api/draws", {
    credentials: "include",
  });
  if (res.status === 403 || res.status === 401) {
    window.location.href = "/login.html";
    return;
  }
  const result = await res.json();
  // result: { drawsForWeek, futureOverrides }
  const draws = result.drawsForWeek || result; // fallback for legacy
  const grouped = groupByDay(draws);
  renderTabs(grouped);
  renderCalendar(grouped);
  window._lastFutureOverrides = result.futureOverrides || [];
  renderFutureOverrides(window._lastFutureOverrides);
}

function groupByDay(draws) {
  // Group by date (YYYY-MM-DD) for week view
  return draws.reduce((acc, draw) => {
    const key = draw.date || draw.day_of_week;
    if (!acc[key]) acc[key] = [];
    acc[key].push(draw);
    return acc;
  }, {});
}

function renderTabs(grouped) {
  const tabContainer = document.querySelector(".day-tabs");
  tabContainer.innerHTML = "";
  const daysToShow = getCurrentWeekDays();
  daysToShow.forEach((dayObj, idx) => {
    const draws = (grouped[dayObj.date] || []).slice().sort((a, b) => a.start_time.localeCompare(b.start_time));
    const isOverridden = draws.some((draw) => draw.is_override);
    const btn = document.createElement("button");
    btn.textContent = dayObj.label;
    // btn.className = (idx === currentDayIndex) ? 'active' : '';
    if (isOverridden) {
      btn.classList.add("overridden-day-btn");
    }
    if (idx === currentDayIndex) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
    btn.onclick = () => {
      currentDayIndex = idx;
      renderCalendar(grouped);
      renderTabs(grouped);
    };
    tabContainer.appendChild(btn);
  });
}

function renderCalendar(grouped) {
  const grid = document.querySelector(".calendar-grid");
  grid.innerHTML = "";

  // Generate time labels (8am to 11pm)
  const labelContainer = document.querySelector(".time-labels");
  labelContainer.innerHTML = "";

  for (let hour = 8; hour <= 23; hour++) {
    const label = document.createElement("div");
    label.style.height = "60px"; // 1 hour = 60px
    label.style.paddingRight = "6px";
    label.style.textAlign = "right";
    label.style.fontSize = "0.75rem";
    label.style.color = "#888";
    label.textContent = `${hour.toString().padStart(2, "0")}:00`;
    labelContainer.appendChild(label);
  }

  const isMobile = window.innerWidth < 700;
  // For week view, get all dates in the current week
  const daysToShow = getCurrentWeekDays();
  const daysToRender = isMobile ? [daysToShow[currentDayIndex]] : daysToShow;

  const HOUR_HEIGHT = 60; // 60px per hour = 1px per minute
  const START_HOUR = 8;
  const TIME_LINE_HEIGHT = 30;
  const TIME_LINE_OFFSET = 25;

  daysToRender.forEach((dayObj, idx) => {
    const dayWrapper = document.createElement("div");
    dayWrapper.className = "day-wrapper";

    const draws = (grouped[dayObj.date] || []).slice().sort((a, b) => a.start_time.localeCompare(b.start_time));
    const isOverridden = draws.some((draw) => draw.is_override);

    // Find all override time ranges for this day
    const overrideRanges = draws
      .filter((draw) => draw.is_override)
      .map((draw) => {
        const [h, m] = draw.start_time.split(":").map(Number);
        const start = h * 60 + m;
        const end = start + draw.duration_minutes;
        return { start, end };
      });

    const dayColumn = document.createElement("div");
    dayColumn.className = "day-column";
    dayWrapper.innerHTML = `<h3 class="day-label${isOverridden ? " overridden-day-label" : ""}">${
      dayObj.label
    }<br><span style='font-size:0.8em;color:#888;'>${dayObj.date}${
      isOverridden ? " <span style='color:#d00;font-size:0.9em;'>(Override)</span>" : ""
    }</span></h3>`;

    // Generate time lines
    for (let h = 1; h <= 31; h++) {
      const line = document.createElement("div");
      line.className = "time-line";
      line.style.top = `${h * TIME_LINE_HEIGHT + TIME_LINE_HEIGHT + TIME_LINE_OFFSET}px`;
      dayWrapper.appendChild(line);
    }

    const now = new Date();
    const startHour = new Date(now.getFullYear(), now.getMonth(), now.getDate(), START_HOUR, 0, 0);
    const endHour = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
    const isBetween = now >= startHour && now <= endHour;

    if (isBetween && currentDayIndex === idx) {
      const currentLine = document.createElement("div");
      currentLine.classList.add("time-line");
      currentLine.classList.add("current-time-line");
      const minutesSinceStart = (now.getHours() - START_HOUR) * 60 + now.getMinutes();
      const topInPixels = (minutesSinceStart / 60) * HOUR_HEIGHT + (TIME_LINE_OFFSET + TIME_LINE_HEIGHT);
      currentLine.style.top = `${topInPixels}px`;
      dayWrapper.appendChild(currentLine);
    }

    dayWrapper.appendChild(dayColumn);
    // Use date string as key for grouping
    draws.forEach((draw) => {
      const [hourStr, minStr] = draw.start_time.split(":");
      const startMinutes = parseInt(hourStr) * HOUR_HEIGHT + parseInt(minStr) - START_HOUR * 60;
      const top = startMinutes;
      const height = draw.duration_minutes;

      // Check if this is a regular draw overlapped by an override
      let faded = false;
      if (!draw.is_override) {
        const drawStart = parseInt(hourStr) * 60 + parseInt(minStr);
        const drawEnd = drawStart + draw.duration_minutes;
        faded = overrideRanges.some((r) => drawStart < r.end && drawEnd > r.start);
      }

      const div = document.createElement("div");
      div.className = "draw-card-abs" + (faded ? " faded-draw" : "");
      div.style.top = `${top}px`;
      div.style.height = `${height}px`;
      div.innerHTML = `
        <strong>${draw.title}${
        draw.is_override ? " <span style='color:#d00;font-size:0.8em;'>(Override)</span>" : ""
      }</strong>
        <span>${draw.start_time} (${draw.duration_minutes} min)</span>
        ${draw.message ? `<span>${draw.message}</span>` : ""}
      `;
      div.onclick = () => openForm(draw);
      dayColumn.appendChild(div);
    });

    grid.appendChild(dayWrapper);
  });
}

function renderFutureOverrides(futureOverrides) {
  const container = document.getElementById("futureOverridesContainer");
  const select = document.getElementById("futureOverridesSelect");
  // Clear previous options except the default
  select.innerHTML = '<option value="">-- Select a future override to edit --</option>';
  if (futureOverrides && futureOverrides.length > 0) {
    container.style.display = "block";
    futureOverrides.forEach((draw) => {
      const option = document.createElement("option");
      option.value = draw.id;
      option.textContent = `${draw.date} - ${draw.title} (${draw.start_time}, ${draw.duration_minutes} min)`;
      select.appendChild(option);
    });
  } else {
    container.style.display = "none";
  }
  select.onchange = () => {
    const selected = futureOverrides.find((d) => d.id == select.value);
    if (selected) openForm(selected);
    select.value = "";
  };
}

// Helper to open the form for a future override by id
function openFormOverride(id) {
  if (!window._lastFutureOverrides) return;
  const draw = window._lastFutureOverrides.find((d) => d.id == id);
  if (draw) openForm(draw);
}

function openForm(draw = null) {
  const modal = document.getElementById("formModal");
  const form = document.getElementById("drawForm");
  document.getElementById("formTitle").textContent = draw ? "Edit Draw" : "Add Draw";
  form.reset();
  form.id.value = draw?.id || "";
  form.day_of_week.value = draw?.day_of_week || "";
  form.override_date.value = draw?.date;
  form.title.value = draw?.title || "";
  form.message.value = draw?.message || "";
  form.start_time.value = draw?.start_time || "";
  form.duration_minutes.value = draw?.duration_minutes || "";
  // Set draw type switch
  setDrawOverride(!!draw?.is_override);
  if (!!draw?.is_override) {
    form.override_date.value = draw.date;
  }
  // Disable draw type switch if editing
  document.getElementById("weeklyBtn").disabled = !!draw;
  document.getElementById("dateBtn").disabled = !!draw;
  document.getElementById("weeklyBtn").classList.toggle("disabled", !!draw);
  document.getElementById("dateBtn").classList.toggle("disabled", !!draw);
  modal.classList.add("active");
}

function closeForm() {
  document.getElementById("formModal").classList.remove("active");
}

async function deleteDraw() {
  if (confirm("Are you sure you want to delete this draw?")) {
    const form = document.getElementById("drawForm");
    const id = form.id.value;
    // Determine if this is an override draw
    const isOverride = form.day_of_week.style.display === "none" || form.day_of_week.value === "";
    const endpoint = isOverride ? `/api/draw-overrides/${id}` : `/api/draws/${id}`;
    const res = await fetch(endpoint, {
      method: "DELETE",
      credentials: "include",
    });
    if (!res.ok) {
      alert("Failed to delete draw.");
    }
    loadDraws(); // reload the UI
    document.getElementById("formModal").classList.remove("active");
  }
}

function setDrawOverride(isOverride) {
  document.getElementById("overrideDateContainer").style.display = isOverride ? "block" : "none";
  document.getElementById("dayOfWeekContainer").style.display = isOverride ? "none" : "block";
  document.getElementById("weeklyBtn").classList.toggle("active", !isOverride);
  document.getElementById("dateBtn").classList.toggle("active", isOverride);
  // Set required attributes
  document.querySelector('[name="override_date"]').required = isOverride;
  document.querySelector('[name="day_of_week"]').required = !isOverride;
  if (!isOverride) {
    document.querySelector('[name="override_date"]').value = "";
  }
}

async function saveDraw(e) {
  e.preventDefault();
  const form = e.target;
  const startTime = form.start_time.value;
  const duration = parseInt(form.duration_minutes.value, 10);
  const timePattern = /^(\d{2}):(\d{2})$/;
  let valid = false;
  if (timePattern.test(startTime)) {
    const [, h, m] = startTime.match(timePattern);
    if (+h >= 0 && +h <= 23 && +m >= 0 && +m <= 59) {
      valid = true;
    }
  }
  if (!valid) {
    alert("Start Time must be in HH:MM format, with hours 00-23 and minutes 00-59.");
    form.start_time.focus();
    return;
  }
  if (isNaN(duration) || duration <= 0 || duration > 300) {
    alert("Duration (minutes) must be a number greater than 0 and less than or equal to 300.");
    form.duration_minutes.focus();
    return;
  }
  const overrideDate = form.override_date.value;
  const data = {
    ...(overrideDate ? { override_date: overrideDate } : { day_of_week: form.day_of_week.value }),
    day_of_week: form.day_of_week.value,
    title: form.title.value,
    message: form.message.value,
    start_time: form.start_time.value,
    duration_minutes: duration,
  };
  const endpoint = overrideDate ? `/api/draw-overrides/${form.id.value}` : `/api/draws/${form.id.value}`;
  if (form.id.value) {
    // Use correct endpoint for edit based on draw type
    await fetch(endpoint, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(data),
    });
  } else {
    await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(data),
    });
  }
  closeForm();
  loadDraws();
}

function getCurrentWeekDays() {
  const today = new Date();
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay());
  const daysToShow = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    const dateStr =
      d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    daysToShow.push({
      label: daysOfWeek[d.getDay()],
      date: dateStr,
    });
  }
  return daysToShow;
}

// Input mask for start_time field
document.addEventListener("DOMContentLoaded", function () {
  const startTimeInput = document.querySelector('input[name="start_time"]');
  if (startTimeInput) {
    startTimeInput.addEventListener("input", function (e) {
      let v = e.target.value.replace(/[^0-9:]/g, "");
      // Only allow up to 5 chars, and force format ##:##
      if (v.length > 5) v = v.slice(0, 5);
      // Insert colon if not present and length > 2
      if (v.length > 2 && v[2] !== ":") {
        v = v.slice(0, 2) + ":" + v.slice(2);
      }
      // Remove extra colons
      v = v.replace(/(\:)(?=.*\:)/g, "");
      // Validate hours and minutes as user types
      const parts = v.split(":");
      if (parts.length === 2) {
        let [h, m] = parts;
        if (h.length > 2) h = h.slice(0, 2);
        if (m.length > 2) m = m.slice(0, 2);
        // Only allow 00-23 for hours
        if (h && (isNaN(h) || +h < 0 || +h > 23)) h = h.slice(0, 1);
        // Only allow 00-59 for minutes
        if (m && (isNaN(m) || +m < 0 || +m > 59)) m = m.slice(0, 1);
        v = h;
        if (m !== undefined) v += ":" + m;
      }
      e.target.value = v;
    });
  }
});

// --- Timer Config Panel Logic ---
async function loadConfig() {
  const res = await fetch('/api/timer/config', { credentials: 'include' });
  if (!res.ok) return;
  const config = await res.json();
  const form = document.getElementById('configForm');
  for (const k in config) {
    if (form[k]) form[k].value = config[k];
  }
  applyConfigToCSS(config);
}

function applyConfigToCSS(config) {
  // Set CSS variables for use in app (can be used in main.css or inline)
  const root = document.documentElement;
  for (const k in config) {
    if (
      k.endsWith('_color') ||
      k.endsWith('_warning') ||
      k.endsWith('_critical') ||
      k.endsWith('_font_size')
    ) {
      root.style.setProperty(`--${k.replace(/_/g, '-')}`, config[k]);
    }
  }
}

async function saveConfig(e) {
  e.preventDefault();
  const form = e.target;
  const data = {};
  for (const el of form.elements) {
    if (el.name) data[el.name] = el.value;
  }
  const res = await fetch('/api/timer/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data)
  });
  if (res.ok) {
    document.getElementById('configStatus').textContent = 'Saved!';
    loadConfig();
    setTimeout(() => { document.getElementById('configStatus').textContent = ''; }, 1500);
  } else {
    document.getElementById('configStatus').textContent = 'Error saving config.';
  }
}


window.addEventListener("resize", loadDraws);
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("drawForm").addEventListener("submit", saveDraw);
    document.getElementById('configForm').addEventListener('submit', saveConfig);
});
loadDraws();
loadConfig();