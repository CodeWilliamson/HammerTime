import { getFullConfig, getCurrentDraw } from "./db.js";
import { getHostIP } from "./util.js";

// Compute the current timer display state (idle / waiting / pre_draw / running / complete)
// Shared by the REST state endpoint and SSE broadcasts.
export function getTimerState() {
  const config = getFullConfig();
  const state = {};

  const currentIp = getHostIP();
  state.adminUrl = currentIp ? `http://${currentIp}/admin` : null;

  const now = new Date();
  const { lastEndedDraw, nextDraw } = getCurrentDraw();

  // Case 1: draw is running or starting soon (within 10 minutes)
  if (nextDraw) {
    const { drawStart, drawEnd } = nextDraw;
    const secondsUntilStart = Math.floor((drawStart - now) / 1000);

    if (now >= drawStart && now < drawEnd) {
      return {
        status: "running",
        drawLabel: nextDraw.title,
        drawMessage: nextDraw.message ?? null,
        targetTime: drawEnd.toISOString(),
        ...state,
      };
    }

    if (secondsUntilStart <= 600 && secondsUntilStart > 0) {
      return {
        status: "pre_draw",
        drawLabel: nextDraw.title,
        drawMessage: nextDraw.message ?? null,
        targetTime: drawStart.toISOString(),
        endTime: drawEnd.toISOString(),
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
    drawLabel: "No draw scheduled",
    drawMessage: null,
    targetTime: null,
    ...state,
  };
}
