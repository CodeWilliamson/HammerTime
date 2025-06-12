import express from "express";
import jwt from "jsonwebtoken";
import bcrypt from "bcryptjs";
import { getUserByUsername } from "./db.js";

const router = express.Router();

const SECRET = process.env.JWT_SECRET || "timertimertimer";

// Login route
router.post("/login", (req, res) => {
  const { username, password } = req.body;
  const user = getUserByUsername(username);
  if (!user || !bcrypt.compareSync(password, user.password_hash)) {
    return res.status(401).json({ error: "Invalid credentials" });
  }

  const token = jwt.sign({ user: username }, SECRET, { expiresIn: "1h" });
  res.cookie("token", token, {
    httpOnly: true,
    sameSite: "strict",
    maxAge: 60 * 60 * 1000, // 1 hour
  });
  res.json({ success: true });
});

// Auth middleware
export function requireAuth(req, res, next) {
  const token = req.cookies.token;
  if (!token) {
    return res.status(403).json({ error: "No token" });
  }

  // const token = authHeader.split(" ")[1];
  try {
    const decoded = jwt.verify(token, SECRET);
    req.user = decoded.user;
    next();
  } catch {
    res.status(403).json({ error: "Invalid or expired token" });
  }
}

export default router;
