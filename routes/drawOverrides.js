import express from "express";
import {
  addDrawOverride,
  updateDrawOverride,
  deleteDrawOverride,
} from "../db.js";
import { broadcastDraws, broadcastTimerState } from "../broadcast.js";
import { requireAuth } from "../auth.js";

const router = express.Router();

// Create a new draw override for a specific date
router.post("/", requireAuth, (req, res) => {
  try {
    const id = addDrawOverride(req.body);
    broadcastDraws();
    broadcastTimerState();
    res.status(201).json({ id });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

// Update an existing draw override
router.put("/:id", requireAuth, (req, res) => {
  try {
    const updated = updateDrawOverride(req.params.id, req.body);
    if (!updated) {
      return res.status(404).json({ error: "Override draw not found" });
    }
    broadcastDraws();
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

// Delete a draw override
router.delete("/:id", requireAuth, (req, res) => {
  try {
    const deleted = deleteDrawOverride(req.params.id);
    if (!deleted) {
      return res.status(404).json({ error: "Draw not found" });
    }
    broadcastDraws();
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

export default router;
