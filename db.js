import Database from 'better-sqlite3';

const db = new Database('./data/schedule.db');

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

export function getTodayDraw() {
  const now = new Date();
  const day = now.toLocaleDateString('en-CA', { weekday: 'long' });

  const stmt = db.prepare(`
    SELECT * FROM draws
    WHERE day_of_week = ?
    ORDER BY start_time ASC
  `);
  const draws = stmt.all(day);

  // Pick the first one that is not already completed
  for (const draw of draws) {
    const [h, m] = draw.start_time.split(":").map(Number);
    const drawStart = new Date(now);
    drawStart.setHours(h, m, 0, 0);
    const drawEnd = new Date(drawStart.getTime() + draw.duration_minutes * 60000);

    if (now < drawEnd) {
      return {
        ...draw,
        drawStart,
        drawEnd
      };
    }
  }

  return null;
}

// db.js additions

export function getDraws() {
  const stmt = db.prepare(`SELECT * FROM draws ORDER BY day_of_week, start_time`);
  return stmt.all();
}

export function addDraw(draw) {
  const stmt = db.prepare(`
    INSERT INTO draws (day_of_week, title, message, start_time, duration_minutes)
    VALUES (@day_of_week, @title, @message, @start_time, @duration_minutes)
  `);
  const info = stmt.run(draw);
  return info.lastInsertRowid;
}

export function updateDraw(id, draw) {
  const stmt = db.prepare(`
    UPDATE draws SET
      day_of_week = @day_of_week,
      title = @title,
      message = @message,
      start_time = @start_time,
      duration_minutes = @duration_minutes
    WHERE id = @id
  `);
  stmt.run({ ...draw, id: Number(id) });
}

export function deleteDraw(id) {
  const stmt = db.prepare(`DELETE FROM draws WHERE id = ?`);
  stmt.run(Number(id));
}
