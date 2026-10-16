import express from "express";
import {
  getCurrentDraw,
  getAllDraws,
  getDrawById,
  addDraw,
  addDrawOverride,
  updateDraw,
  deleteDraw,
  deleteDrawOverride,
  updateDrawOverride,
  getFullConfig,
  updateConfig,
} from "./db.js";
import authRouter, { requireAuth, SECRET } from "./auth.js";
import { getHostIP } from "./util.js";
import cookieParser from "cookie-parser";
import dotenv from "dotenv";
import { readFileSync } from "fs";
import jwt from "jsonwebtoken";
import { WebSocketServer } from "ws";
dotenv.config();

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());
app.use(cookieParser());
app.use(express.static("public"));

app.get("/admin", (req, res) => {
  res.redirect("/admin.html");
});

app.get("/api/version", (req, res) => {
  res.json({ version });
});

// Auth routes
app.use("/auth", authRouter);

// --- Timer state (shared by the REST route and WS broadcasts) ---

function getTimerState() {
  const config = getFullConfig();
  const state = {};

  const currentIp = getHostIP();
  state.adminUrl = currentIp ? `http://${currentIp}/admin` : null;

  const now = new Date();
  const { lastEndedDraw, nextDraw } = getCurrentDraw();

  // Case 1: draw is running or starting soon
  if (nextDraw) {
    const { drawStart, drawEnd } = nextDraw;
    const secondsUntilStart = Math.floor((drawStart - now) / 1000);
    const secondsUntilEnd = Math.floor((drawEnd - now) / 1000);

    if (now >= drawStart && now < drawEnd) {
      return {
        status: "running",
        timeRemaining: secondsUntilEnd,
        drawLabel: nextDraw.title,
        drawMessage: nextDraw.message ?? null,
        targetTime: drawEnd.toISOString(),
        ...state,
      };
    }

    if (secondsUntilStart <= 600 && secondsUntilStart > 0) {
      return {
        status: "pre_draw",
        timeRemaining: secondsUntilStart,
        drawLabel: nextDraw.title,
        drawMessage: nextDraw.message ?? null,
        targetTime: drawStart.toISOString(),
        ...state,
      };
    }
  }

  // Case 2: recently ended draw (< 10 minutes ago)
  if (lastEndedDraw) {
    const secondsSinceEnd = Math.floor((now - lastEndedDraw.drawEnd) / 1000);
    if (secondsSinceEnd <= 600) {
      return {
        status: "complete",
        timeRemaining: 0,
        drawLabel: lastEndedDraw.title,
        drawMessage: lastEndedDraw.message ?? null,
        targetTime: lastEndedDraw.drawEnd.toISOString(),
        ...state,
      };
    }
  }

  // Case 3: no draw now, show next one if it exists
  if (nextDraw) {
    return {
      status: "waiting",
      timeRemaining: 0,
      nextDrawStart: nextDraw.drawStart.toISOString(),
      targetTime: nextDraw.drawStart.toISOString(),
      nextDrawTitle: nextDraw.title,
      nextDrawMessage: nextDraw.message ?? null,
      ...state,
    };
  }

  // Case 4: no draws today
  return {
    status: "idle",
    timeRemaining: 0,
    drawLabel: "No draw scheduled",
    drawMessage: null,
    targetTime: null,
    ...state,
  };
}

// Existing timer state route (kept as a REST fallback / initial fetch)
app.get("/api/timer/state", (req, res) => {
  const clientConfigTimestamp = new Date(req.query.lastConfigSeenAt || 0);
  const config = getFullConfig();
  const configChanged = new Date(config.updated_at) > clientConfigTimestamp;
  const state = getTimerState();
  // Append config only if changed since the client last saw it
  if (configChanged) {
    state.config = { ...config, updated_at: config.updated_at };
  }
  res.json(state);
});

app.get("/api/timer/closest-draw-duration", (req, res) => {
  const { lastEndedDraw, nextDraw } = getCurrentDraw();
  const draw = nextDraw ?? lastEndedDraw;
  res.json({ durationMinutes: draw?.duration_minutes ?? null });
});

// --- CRUD API for draws ---

app.get("/api/draws", requireAuth, (req, res) => {
  const draws = getAllDraws();
  res.json(draws);
});

app.get("/api/draws/:id", requireAuth, (req, res) => {
  const id = parseInt(req.params.id);
  const draw = getDrawById(id);
  if (!draw) {
    return res.status(404).json({ error: 'Draw not found' });
  }
  res.json(draw);
});



// Timer config API (for dynamic CSS)
app.get("/api/timer/config", requireAuth, (req, res) => {
  const config = getFullConfig();
  res.json(config);
});

// --- WebSocket server (pushes timer state, config, and draws to clients) ---

const server = app.listen(port, '0.0.0.0', () => {
  console.log(`Curling timer backend running on http://localhost:${port}`);
});

const wss = new WebSocketServer({ server, path: "/ws" });
const clients = new Set();

// Stringify and send a message to every connected client
function broadcast(msg) {
  const data = JSON.stringify(msg);
  clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(data);
    }
  });
}

// Push the latest computed timer state to all connected clients
function broadcastTimerState() {
  broadcast({ type: "timer_state", ...getTimerState() });
}

// Push the latest display config to all connected clients
function broadcastConfig() {
  broadcast({ type: "config", ...getFullConfig() });
}

// Push the latest draw schedule to all connected clients
function broadcastDraws() {
  const { drawsForWeek, futureOverrides } = getAllDraws();
  broadcast({ type: "draws", drawsForWeek, futureOverrides });
}

wss.on("connection", (ws, req) => {
  clients.add(ws);
  ws.on("close", () => clients.delete(ws));
  ws.on("error", () => clients.delete(ws));

  // Reply to client heartbeats so the client knows the connection is alive
  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === "ping") {
        ws.send(JSON.stringify({ type: "pong" }));
      }
    } catch {
      // Ignore malformed client messages
    }
  });

  // Send the full current state immediately so the client syncs without waiting
  // for a change to occur.
  const config = getFullConfig();
  const state = getTimerState();
  ws.send(
    JSON.stringify({
      type: "hello",
      timer_state: state,
      config,
      adminUrl: state.adminUrl,
    })
  );
});

// --- Hook broadcasts into mutation routes ---

app.put("/api/timer/config", requireAuth, (req, res) => {
  const ok = updateConfig(req.body);
  if (!ok) return res.status(400).json({ error: 'No valid fields to update' });
  // Push the new config + timer state to every client so all displays update live
  broadcastConfig();
  broadcastTimerState();
  res.status(204).end();
});

app.post("/api/draws", requireAuth, (req, res) => {
  try {
    const id = addDraw(req.body);
    broadcastDraws();
    broadcastTimerState();
    res.status(201).json({ id });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.put("/api/draws/:id", requireAuth, (req, res) => {
  try {
    updateDraw(req.params.id, req.body);
    broadcastDraws();
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.delete("/api/draws/:id", requireAuth, (req, res) => {
  try {
    const deleted = deleteDraw(req.params.id);
    if (!deleted) {
      return res.status(404).json({ error: 'Draw not found' });
    }
    broadcastDraws();
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.post("/api/draw-overrides", requireAuth, (req, res) => {
  try {
    const id = addDrawOverride(req.body);
    broadcastDraws();
    broadcastTimerState();
    res.status(201).json({ id });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.put("/api/draw-overrides/:id", requireAuth, (req, res) => {
  try {
    const updated = updateDrawOverride(req.params.id, req.body);
    if (!updated) {
      return res.status(404).json({ error: 'Override draw not found' });
    }
    broadcastDraws();
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.delete("/api/draw-overrides/:id", requireAuth, (req, res) => {
  try {
    const deleted = deleteDrawOverride(req.params.id);
    if (!deleted) {
      return res.status(404).json({ error: 'Draw not found' });
    }
    broadcastDraws();
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});
