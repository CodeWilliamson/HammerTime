import { WebSocketServer } from "ws";
import { getTimerState } from "./timerState.js";
import { getFullConfig } from "./db.js";

const clients = new Set();
let wss = null;

// Attach the WebSocket server to the HTTP server and handle client connections.
export function initBroadcast(httpServer) {
  wss = new WebSocketServer({ server: httpServer, path: "/ws" });

  wss.on("connection", (ws) => {
    // log connection ONLY on debug flag
    if (process.env.DEBUG) {
      console.log("New WebSocket connection established.");
    }
    clients.add(ws);
    ws.on("close", () => {
      if (process.env.DEBUG) {
        console.log("WebSocket connection closed.");
      }
      clients.delete(ws);
    });
    ws.on("error", () => {
      if (process.env.DEBUG) {
        console.log("WebSocket connection error.");
      }
      clients.delete(ws);
    });

    // Reply to client heartbeats so the client knows the connection is alive
    ws.on("message", (data) => {
      try {
        const msg = JSON.parse(data.toString());
        if (process.env.DEBUG) {
          console.log("Received message from client:", msg);
        }
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

  // Time-driven state transitions (running -> complete, complete -> next draw,
  // etc.) are not tied to any REST write, so nothing else would push them.
  // Periodically re-broadcast the computed state so clients always converge
  // (worst case: ~60s of stale display at a draw boundary). Clients only
  // adopt timeRemaining on a status change, so regular pushes are harmless.
  setInterval(broadcastTimerState, 60_000);
}

// Stringify and send a message to every connected client.
function broadcast(msg) {
  const data = JSON.stringify(msg);
  if (process.env.DEBUG) {
    console.log(`Broadcasting message to ${clients.size} clients:`, msg);
  }
  clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(data);
    }
  });
}

// Push the latest computed timer state to all connected clients.
export function broadcastTimerState() {
  broadcast({ type: "timer_state", ...getTimerState() });
}

// Push the latest display config to all connected clients.
export function broadcastConfig() {
  broadcast({ type: "config", ...getFullConfig() });
}
