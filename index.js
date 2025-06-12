import express from "express";
import { getCurrentDraw, getConfig, getAllDraws, getDrawById, addDraw, updateDraw, deleteDraw } from "./db.js";
import authRouter, { requireAuth } from "./auth.js";
import cookieParser from "cookie-parser";

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());
app.use(cookieParser());
app.use(express.static("public"));

app.get('/admin', (req, res) => {
  res.redirect('/admin.html');
});

// Auth routes
app.use('/auth', authRouter);

// Existing timer state route
app.get("/api/timer/state", (req, res) => {
  // Check if config has changed
  const clientConfigTimestamp = new Date(req.query.lastConfigSeenAt || 0);
  const config = getConfig();
  const configChanged = new Date(config.updated_at) > clientConfigTimestamp;
  let state = {};
  // Append config only if changed
  if (configChanged) {
    state.config = {
      ...config,
      updated_at: config.updated_at
    };
  }

  const now = new Date();
  const { lastEndedDraw, nextDraw } = getCurrentDraw();

  // Case 1: draw is running or starting soon
  if (nextDraw) {
    const { drawStart, drawEnd } = nextDraw;
    const secondsUntilStart = Math.floor((drawStart - now) / 1000);
    const secondsUntilEnd = Math.floor((drawEnd - now) / 1000);
    
    // console.log(`now: ${now}, drawStart: ${drawStart}, drawEnd: ${drawEnd}`);

    if (now >= drawStart && now < drawEnd) {
      return res.json({
        status: "running",
        timeRemaining: secondsUntilEnd,
        drawLabel: nextDraw.title,
        drawMessage: nextDraw.message ?? null,
        targetTime: drawEnd.toISOString(),
        ...state,
      });
    }

    if (secondsUntilStart <= 600 && secondsUntilStart > 0) {
      return res.json({
        status: "pre_draw",
        timeRemaining: secondsUntilStart,
        drawLabel: nextDraw.title,
        drawMessage: nextDraw.message ?? null,
        targetTime: drawStart.toISOString(),
        ...state,
      });
    }
  }

  // Case 2: recently ended draw (< 10 minutes ago)
  if (lastEndedDraw) {
    const secondsSinceEnd = Math.floor((now - lastEndedDraw.drawEnd) / 1000);
    if (secondsSinceEnd <= 600) {
      return res.json({
        status: "complete",
        timeRemaining: 0,
        drawLabel: lastEndedDraw.title,
        drawMessage: lastEndedDraw.message ?? null,
        targetTime: lastEndedDraw.drawEnd.toISOString(),
        ...state,
      });
    }
  }

  // Case 3: no draw now, show next one if it exists
  if (nextDraw) {
    return res.json({
      status: "waiting",
      timeRemaining: 0,
      nextDrawStart: nextDraw.drawStart.toISOString(),
      targetTime: nextDraw.drawStart.toISOString(),
      nextDrawTitle: nextDraw.title,
      nextDrawMessage: nextDraw.message ?? null,
      ...state,
    });
  }

  // Case 4: no draws today
  return res.json({
    status: "idle",
    timeRemaining: 0,
    drawLabel: "No draw scheduled",
    drawMessage: null,
    targetTime: null,
    ...state,
  });
});

// CRUD API for draws

app.get("/api/draws", requireAuth,(req, res) => {
  const draws = getAllDraws();
  res.json(draws);
});

app.get('/api/draws/:id', requireAuth, (req, res) => {
  const id = parseInt(req.params.id);
  const draw = getDrawById(id);
  if (!draw) {
    return res.status(404).json({ error: 'Draw not found' });
  }
  res.json(draw);
});

app.post("/api/draws", requireAuth, (req, res) => {
  try {
    const id = addDraw(req.body);
    res.status(201).json({ id });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.put("/api/draws/:id", requireAuth, (req, res) => {
  try {
    updateDraw(req.params.id, req.body);
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.delete("/api/draws/:id", requireAuth, (req, res) => {
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
