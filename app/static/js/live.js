// Live updates from the server over a WebSocket. Reconnects by itself.

const handlers = new Map();
const PING_INTERVAL = 25_000;

let socket = null;
let wanted = false;
let attempts = 0;
let pingTimer = null;
let retryTimer = null;

export function on(type, handler) {
  if (!handlers.has(type)) handlers.set(type, []);
  handlers.get(type).push(handler);
}

function emit(type, event) {
  for (const handler of handlers.get(type) || []) handler(event);
}

export function isLive() {
  return socket !== null && socket.readyState === WebSocket.OPEN;
}

export function connectLive() {
  wanted = true;
  if (socket === null && retryTimer === null) open();
}

export function disconnectLive() {
  wanted = false;
  clearTimeout(retryTimer);
  retryTimer = null;
  socket?.close();
}

function open() {
  retryTimer = null;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws`);
  socket = ws;

  ws.addEventListener("open", () => {
    attempts = 0;
    pingTimer = setInterval(() => ws.send("ping"), PING_INTERVAL);
    emit("open", {});
  });
  ws.addEventListener("message", (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    if (event && typeof event.type === "string") emit(event.type, event);
  });
  ws.addEventListener("close", (event) => {
    clearInterval(pingTimer);
    if (socket === ws) socket = null;
    emit("close", event);
    if (wanted) {
      const delay = Math.min(30_000, 1000 * 2 ** attempts);
      attempts += 1;
      retryTimer = setTimeout(open, delay);
    }
  });
}
