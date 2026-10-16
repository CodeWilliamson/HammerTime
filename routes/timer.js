import express from "express";
import { getTimerState } from "../timerState.js";
import { getCurrentDraw, getFullConfig, updateConfig } from "../db.js";
import { broadcastTimerState, broadcastConfig } from "../broadcast.js";
import { requireAuth } from "../auth.js";

const router = express.Router();

// Current timer display state (REST fallback / initial fetch)
router.get("/state", (req, res) => {
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

// Duration (minutes) of the closest upcoming or most recent draw
router.get("/closest-draw-duration", (req, res) => {
  const { lastEndedDraw, nextDraw } = getCurrentDraw();
  const draw = nextDraw ?? lastEndedDraw;
  res.json({ durationMinutes: draw?.duration_minutes ?? null });
});

// Get the timer display config (for dynamic CSS)
router.get("/config", requireAuth, (req, res) => {
  const config = getFullConfig();
  res.json(config);
});

// Update timer config fields and push changes live to all clients
router.put("/config", requireAuth, (req, res) => {
  const ok = updateConfig(req.body);
  if (!ok) return res.status(400).json({ error: "No valid fields to update" });
  // Push the new config + timer state to every client so all displays update live
  broadcastConfig();
  broadcastTimerState();
  res.status(204).end();
});

export default router;
