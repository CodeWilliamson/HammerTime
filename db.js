import Database from "better-sqlite3";

const db = new Database("./data/schedule.db");
import bcrypt from "bcryptjs";

// Initialize table if not exists
db.exec(`
  CREATE TABLE IF NOT EXISTS draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    start_time TEXT NOT NULL,  -- e.g., "19:00"
    duration_minutes INTEGER NOT NULL
  );
`);

db.exec(`
  CREATE TABLE IF NOT EXISTS draw_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                -- ISO format "YYYY-MM-DD"
    title TEXT NOT NULL,
    message TEXT,
    start_time TEXT NOT NULL,          -- "HH:mm"
    duration_minutes INTEGER NOT NULL
  );
`);

db.exec(`
  CREATE TABLE IF NOT EXISTS timer_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  background_color VARCHAR(20) NOT NULL DEFAULT '#111111',
  timer_color VARCHAR(20) NOT NULL DEFAULT '#eeeeee',
  status_color VARCHAR(20) NOT NULL DEFAULT '#eeeeee',
  message_color VARCHAR(20) NOT NULL DEFAULT '#cccccc',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
`);

const existingConfigCount = db.prepare(`SELECT COUNT(*) as count FROM timer_config`).get().count;

if (existingConfigCount === 0) {
  db.prepare(
    `
    INSERT INTO timer_config (background_color, timer_color, status_color, message_color)
    VALUES (@background_color, @timer_color, @status_color, @message_color)
  `
  ).run({
    background_color: "#111111",
    timer_color: "#eeeeee",
    status_color: "#eeeeee",
    message_color: "#cccccc",
  });
}

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
  );
`);

const adminExists = db.prepare(`SELECT COUNT(*) AS count FROM users`).get().count;
if (adminExists === 0) {
  const hash = bcrypt.hashSync("timer", 10);
  db.prepare(`INSERT INTO users (username, password_hash) VALUES (?, ?)`).run("timer", hash);
}

export function getCurrentDraw() {
  const now = new Date();
  // Use local timezone for date string
  const isoDate = now.getFullYear() + '-' +
    String(now.getMonth() + 1).padStart(2, '0') + '-' +
    String(now.getDate()).padStart(2, '0');
  const overrideStmt = db.prepare('SELECT * FROM draw_overrides WHERE date = ?');
  const overrides = overrideStmt.all(isoDate);
  const day = now.toLocaleDateString("en-CA", { weekday: "long" });
  const stmt = db.prepare(`
    SELECT * FROM draws
    WHERE day_of_week = ?
    ORDER BY start_time ASC
  `);
  const weeklyDraws = stmt.all(day);

  let draws = [];
  if (overrides.length > 0) {
    // Exclude weekly draws that overlap with any override
    const nonOverlappingWeeklyDraws = weeklyDraws.filter(wd => {
      const wdStart = parseTimeToMinutes(wd.start_time);
      const wdEnd = wdStart + wd.duration_minutes;
      return !overrides.some(ov => {
        const ovStart = parseTimeToMinutes(ov.start_time);
        const ovEnd = ovStart + ov.duration_minutes;
        return wdStart < ovEnd && wdEnd > ovStart;
      });
    });
    draws = [...overrides, ...nonOverlappingWeeklyDraws];
  } else {
    // No overrides, just use weekly draws
    draws = weeklyDraws;
  }

  let lastEndedDraw = null;
  let nextDraw = null;

  for (const draw of draws) {
    const [h, m] = draw.start_time.split(":").map(Number);
    const drawStart = new Date(now);
    drawStart.setHours(h, m, 0, 0);
    const drawEnd = new Date(drawStart.getTime() + draw.duration_minutes * 60000);

    if (now >= drawEnd) {
      // Save most recently completed draw
      if (!lastEndedDraw || drawEnd > lastEndedDraw.drawEnd) {
        lastEndedDraw = { ...draw, drawStart, drawEnd };
      }
    } else {
      // First upcoming or currently running draw
      nextDraw = { ...draw, drawStart, drawEnd };
      break;
    }
  }

  // Return both so /api/timer/state can decide what to do
  return { lastEndedDraw, nextDraw };
}

// Helper function to convert HH:MM to minutes since midnight
function parseTimeToMinutes(timeStr) {
  const [h, m] = timeStr.split(":").map(Number);
  return h * 60 + m;
}

export function getConfig() {
  const stmt = db.prepare(`
    SELECT background_color, timer_color, status_color, message_color, updated_at
    FROM timer_config
    ORDER BY updated_at DESC
    LIMIT 1
  `);
  return stmt.get();
}

export function addDrawOverride(draw) {
  const stmt = db.prepare(`
    INSERT INTO draw_overrides (date, title, message, start_time, duration_minutes)
    VALUES (?, ?, ?, ?, ?)
  `);
  const result = stmt.run(draw.date, draw.title, draw.message, draw.start_time, draw.duration_minutes);
  return { id: result.lastInsertRowid, override: true };
}

export function addDraw(draw) {
    // Save as recurring draw
    const stmt = db.prepare(`
      INSERT INTO draws (day_of_week, title, message, start_time, duration_minutes)
      VALUES (?, ?, ?, ?, ?)
    `);
    const result = stmt.run(draw.day_of_week, draw.title, draw.message, draw.start_time, draw.duration_minutes);
    return { id: result.lastInsertRowid, override: false };
}

export function updateDraw(id, updates) {
  const stmt = db.prepare(`
    UPDATE draws
    SET day_of_week = ?, title = ?, message = ?, start_time = ?, duration_minutes = ?
    WHERE id = ?
  `);
  const result = stmt.run(
    updates.day_of_week,
    updates.title,
    updates.message,
    updates.start_time,
    updates.duration_minutes,
    id
  );
  return result.changes > 0;
}

export function deleteDraw(id, isOverride = false) {
  if (isOverride) {
    const stmt = db.prepare(`DELETE FROM draw_overrides WHERE id = ?`);
    const result = stmt.run(id);
    return result.changes > 0;
  } else {
    const stmt = db.prepare(`DELETE FROM draws WHERE id = ?`);
    const result = stmt.run(id);
    return result.changes > 0;
  }
}

export function deleteDrawOverride(id) {
  const stmt = db.prepare(`DELETE FROM draw_overrides WHERE id = ?`);
  const result = stmt.run(id);
  return result.changes > 0;
}

export function getAllDraws() {
    // Get all draw_overrides for today and future in one query
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    const overrideStmt = db.prepare('SELECT * FROM draw_overrides WHERE date >= ? ORDER BY date ASC, start_time ASC');
    const allOverrides = overrideStmt.all(todayStr);
    // Map: date string -> array of overrides
    const overridesByDate = {};
    for (const o of allOverrides) {
      if (!overridesByDate[o.date]) overridesByDate[o.date] = [];
      overridesByDate[o.date].push({ ...o, is_override: true });
    }
    // Get all recurring draws
    const drawsStmt = db.prepare('SELECT * FROM draws ORDER BY day_of_week ASC, start_time ASC');
    const allDraws = drawsStmt.all();
    // Build week view
    const drawsForWeek = [];
    const weekStart = new Date(today);
    weekStart.setDate(today.getDate() - today.getDay());
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekStart.getDate() + 6);

    for (let i = 0; i < 7; i++) {
      const d = new Date(weekStart);
      d.setDate(weekStart.getDate() + i);
      const dateStr = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      const dayOfWeekStr = d.toLocaleDateString('en-CA', { weekday: 'long' });

      // Get all weekly draws for this day
      const weeklyDraws = allDraws
        .filter(r => r.day_of_week === dayOfWeekStr)
        .map(r => ({ ...r, day_of_week: dayOfWeekStr, date: dateStr }));

      // Get all overrides for this date
      const overrides = (overridesByDate[dateStr] || []).map(o => ({ ...o, date: o.date, is_override: true }));

      // Build a map of start_time to override for quick lookup
      const overrideTimes = new Set(overrides.map(o => o.start_time));

      // Add overrides first (they take precedence)
      overrides.forEach(o => drawsForWeek.push(o));

      // Add weekly draws that do NOT overlap with an override
      weeklyDraws
        .filter(wd => !overrideTimes.has(wd.start_time))
        .forEach(wd => drawsForWeek.push(wd));
    }

    // Collect future overrides (after this week)
    const futureOverrides = allOverrides.filter(o => {
      // Compare using only the date part (ignore time zone issues)
      const oDate = new Date(o.date + 'T00:00:00');
      const weekEndDate = new Date(weekEnd.getFullYear(), weekEnd.getMonth(), weekEnd.getDate());
      return oDate > weekEndDate;
    }).map(o => ({ ...o, is_override: true }));

    return { drawsForWeek, futureOverrides };
}

export function getDrawById(id) {
  const stmt = db.prepare(`SELECT * FROM draws WHERE id = ?`);
  return stmt.get(id);
}

export function getUserByUsername(username) {
  const stmt = db.prepare(`SELECT * FROM users WHERE username = ?`);
  return stmt.get(username.toLowerCase());
}

export function updatePassword(username, newPassword) {
  const hash = bcrypt.hashSync(newPassword, 10);
  const stmt = db.prepare(`UPDATE users SET password_hash = ? WHERE username = ?`);
  const result = stmt.run(hash, username.toLowerCase());
  return result.changes > 0;
}

export function updateDrawOverride(id, updates) {
  const stmt = db.prepare(`
    UPDATE draw_overrides
    SET date = ?, title = ?, message = ?, start_time = ?, duration_minutes = ?
    WHERE id = ?
  `);
  const result = stmt.run(
    updates.override_date || updates.date, // allow either field name
    updates.title,
    updates.message,
    updates.start_time,
    updates.duration_minutes,
    id
  );
  return result.changes > 0;
}
