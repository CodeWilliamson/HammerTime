import express from "express";
import { readFileSync } from "fs";
import cookieParser from "cookie-parser";
import dotenv from "dotenv";
import authRouter from "./auth.js";
import timerRouter from "./routes/timer.js";
import drawsRouter from "./routes/draws.js";
import drawOverrideRoutes from "./routes/drawOverrides.js";
import { handleEvents } from "./broadcast.js";

dotenv.config();

const { version } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8")
);

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());
app.use(cookieParser());
app.use(express.static("public"));

// Redirect /admin to the admin HTML page
app.get("/admin", (req, res) => {
  res.redirect("/admin.html");
});

// API version metadata
app.get("/api/version", (req, res) => {
  res.json({ version });
});

// Mount REST route modules
app.use("/auth", authRouter);
app.use("/api/timer", timerRouter);
app.use("/api/draws", drawsRouter);
app.use("/api/draw-overrides", drawOverrideRoutes);

// Server-Sent Events stream: live timer state + config for all display pages
app.get("/events", handleEvents);

// Start the HTTP server
app.listen(port, "0.0.0.0", () => {
  console.log(`Curling timer backend running on http://localhost:${port}`);
});
