// Single source of truth: talks only to public, unauthenticated endpoints.
const BASE = import.meta.env.VITE_API_BASE || "";

async function get(path, signal) {
  const r = await fetch(`${BASE}${path}`, signal ? { signal } : undefined);
  if (!r.ok) throw new Error(`GET ${path}: ${r.status}`);
  const body = await r.json();
  return body.data;
}

export const api = {
  events: (limit = 24, since = "", signal) =>
    get(`/api/v1/events?limit=${limit}${since ? `&since=${since}` : ""}`, signal),
  leaderboard: (sort = "level", signal) => get(`/api/v1/leaderboard?sort=${sort}`, signal),
  map: (signal) => get(`/api/v1/world/map`, signal),
  state: (signal) => get(`/api/v1/world/state`, signal),
  agent: (id, signal) => get(`/api/v1/agents/${id}`, signal),
  streamURL: () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const host = new URL(BASE || location.href).host || location.host;
    const prefix = BASE.startsWith("http") ? new URL(BASE).host : host;
    return `${proto}://${prefix}/api/v1/events/stream`;
  },
};
