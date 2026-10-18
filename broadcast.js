import { getTimerState } from "./timerState.js";
import { getFullConfig } from "./db.js";

// Connected SSE responses (one per subscribed client/page).
const clients = new Set();
let timersStarted = false;

// Subscribe an HTTP response to the Server-Sent Events stream at GET /events.
// On connect the client gets a full snapshot ("hello"), then named events
// ("timer_state", "config") whenever something changes — plus periodic
// comment heartbeats to keep intermediaries from closing idle streams.
export function handleEvents(req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    // Tell any reverse proxy in front of us never to buffer this stream.
    "X-Accel-Buffering": "no",
  });
  if (res.flushHeaders) res.flushHeaders();

  clients.add(res);
  if (process.env.DEBUG) {
    console.log(`SSE client connected (${clients.size} total).`);
  }
  req.on("close", () => {
    clients.delete(res);
    if (process.env.DEBUG) {
      console.log(`SSE client disconnected (${clients.size} total).`);
    }
  });

  // Full snapshot on every (re)connect. Messages are snapshots, not an event
  // log, so replaying missed ids is unnecessary — resending current state is
  // both simpler and correct (covers EventSource auto-reconnects too).
  const config = getFullConfig();
  const state = getTimerState();
  send(res, "hello", {
    timer_state: state,
    config,
    adminUrl: state.adminUrl,
  });

  // Start the periodic timers once the first client arrives.
  if (!timersStarted) {
    timersStarted = true;
    startTimers();
  }
}

// Start the background timers that keep clients converging.
function startTimers() {
  // Time-driven state transitions (running -> complete, complete -> next draw,
  // etc.) are not tied to any REST write, so nothing else would push them.
  // Periodically re-broadcast the computed state so clients always converge
  // (worst case: ~60s of stale display at a draw boundary). Clients only
  // adopt timeRemaining on a status change, so regular pushes are harmless.
  setInterval(broadcastTimerState, 60_000);

  // Comment heartbeat: keeps long-lived streams alive through proxies and
  // lets clients notice a dead connection.
  setInterval(heartbeat, 20_000);
}

// Write a single named SSE event to one client.
function send(res, type, payload) {
  if (res.destroyed || res.writableEnded) return;
  res.write(`event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`);
}

// Write an SSE comment (ignored by EventSource, but counts as traffic).
function heartbeat() {
  clients.forEach((res) => {
    if (!res.destroyed && !res.writableEnded) res.write(": keep-alive\n\n");
  });
}

// Send a message to every connected client.
function broadcast(msg) {
  if (process.env.DEBUG) {
    console.log(`Broadcasting message to ${clients.size} clients:`, msg);
  }
  clients.forEach((res) => send(res, msg.type, msg));
}

// Push the latest computed timer state to all connected clients.
export function broadcastTimerState() {
  broadcast({ type: "timer_state", ...getTimerState() });
}

// Push the latest display config to all connected clients.
export function broadcastConfig() {
  broadcast({ type: "config", ...getFullConfig() });
}
