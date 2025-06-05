import express from 'express';
import { getTodayDraw, getDraws, addDraw, updateDraw, deleteDraw } from './db.js';

const app = express();
const port = 3000;

app.use(express.json());
app.use(express.static("public"));

// Existing timer state route
app.get('/api/timer/state', (req, res) => {
  const now = new Date();
  const draw = getTodayDraw();

  if (!draw) {
    return res.json({
      status: "idle",
      timeRemaining: 0,
      drawLabel: "No draw scheduled",
      targetTime: null
    });
  }

  let status, remaining;
  const { drawStart, drawEnd } = draw;

  if (now < drawStart) {
    status = "pre_draw";
    remaining = Math.floor((drawStart - now) / 1000);
  } else if (now >= drawStart && now < drawEnd) {
    status = "running";
    remaining = Math.floor((drawEnd - now) / 1000);
  } else {
    status = "complete";
    remaining = 0;
  }

  res.json({
    status,
    timeRemaining: remaining,
    drawLabel: draw.title, // <-- fix from your original "draw.label"
    targetTime: drawStart.toISOString()
  });
});

// CRUD API for draws

app.get('/api/draws', (req, res) => {
  const draws = getDraws();
  res.json(draws);
});

app.post('/api/draws', (req, res) => {
  try {
    const id = addDraw(req.body);
    res.status(201).json({ id });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.put('/api/draws/:id', (req, res) => {
  try {
    updateDraw(req.params.id, req.body);
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.delete('/api/draws/:id', (req, res) => {
  try {
    deleteDraw(req.params.id);
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.listen(port, () => {
  console.log(`Curling timer backend running on http://localhost:${port}`);
});
