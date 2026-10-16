import express from "express";
import {
  getAllDraws,
  getDrawById,
  addDraw,
  updateDraw,
  deleteDraw,
} from "../db.js";
import { broadcastTimerState } from "../broadcast.js";
import { requireAuth } from "../auth.js";

const router = express.Router();

// List all draws (weekly + overrides)
router.get("/", requireAuth, (req, res) => {
  const draws = getAllDraws();
  res.json(draws);
});

// Get a single recurring draw by id
router.get("/:id", requireAuth, (req, res) => {
  const id = parseInt(req.params.id);
  const draw = getDrawById(id);
  if (!draw) {
    return res.status(404).json({ error: "Draw not found" });
  }
  res.json(draw);
});

// Create a new recurring draw
router.post("/", requireAuth, (req, res) => {
  try {
    const id = addDraw(req.body);
    broadcastTimerState();
    res.status(201).json({ id });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

// Update an existing recurring draw
router.put("/:id", requireAuth, (req, res) => {
  try {
    updateDraw(req.params.id, req.body);
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

// Delete a recurring draw
router.delete("/:id", requireAuth, (req, res) => {
  try {
    const deleted = deleteDraw(req.params.id);
    if (!deleted) {
      return res.status(404).json({ error: "Draw not found" });
    }
    broadcastTimerState();
    res.status(204).end();
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

export default router;
