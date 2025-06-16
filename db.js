import Database from "better-sqlite3";

const db = new Database("./data/schedule.db");
import bcrypt from 'bcryptjs';

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
  db.prepare(`
    INSERT INTO timer_config (background_color, timer_color, status_color, message_color)
    VALUES (@background_color, @timer_color, @status_color, @message_color)
  `).run({
    background_color: '#111111',
    timer_color: '#eeeeee',
    status_color: '#eeeeee',
    message_color: '#cccccc'
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
  const day = now.toLocaleDateString("en-CA", { weekday: "long" });

  const stmt = db.prepare(`
    SELECT * FROM draws
    WHERE day_of_week = ?
    ORDER BY start_time ASC
  `);
  const draws = stmt.all(day);

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

export function getConfig() {
  const stmt = db.prepare(`
    SELECT background_color, timer_color, status_color, message_color, updated_at
    FROM timer_config
    ORDER BY updated_at DESC
    LIMIT 1
  `);
  return stmt.get();
}

export function addDraw(draw) {
  const stmt = db.prepare(`
    INSERT INTO draws (day_of_week, title, message, start_time, duration_minutes)
    VALUES (?, ?, ?, ?, ?)
  `);
  const result = stmt.run(draw.day_of_week, draw.title, draw.message, draw.start_time, draw.duration_minutes);
  return result.lastInsertRowid;
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

export function deleteDraw(id) {
  const stmt = db.prepare(`DELETE FROM draws WHERE id = ?`);
  const result = stmt.run(id);
  return result.changes > 0;
}

export function getAllDraws(dayOfWeek = null) {
  if (dayOfWeek) {
    const stmt = db.prepare(`
      SELECT * FROM draws
      WHERE day_of_week = ?
      ORDER BY start_time ASC
    `);
    return stmt.all(dayOfWeek);
  } else {
    const stmt = db.prepare(`
      SELECT * FROM draws
      ORDER BY
        CASE day_of_week
          WHEN 'Sunday' THEN 0
          WHEN 'Monday' THEN 1
          WHEN 'Tuesday' THEN 2
          WHEN 'Wednesday' THEN 3
          WHEN 'Thursday' THEN 4
          WHEN 'Friday' THEN 5
          WHEN 'Saturday' THEN 6
        END,
        start_time ASC
    `);
    return stmt.all();
  }
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