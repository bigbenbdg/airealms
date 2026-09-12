// Single source of truth: talks only to public, unauthenticated endpoints.
const BASE = import.meta.env.VITE_API_BASE || "";

async function get(path) {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path}: ${r.status}`);
  const body = await r.json();
  return body.data;
}

export const api = {
  events: (limit = 24, since = "") =>
    get(`/api/v1/events?limit=${limit}${since ? `&since=${since}` : ""}`),
  leaderboard: (sort = "level") => get(`/api/v1/leaderboard?sort=${sort}`),
  map: () => get(`/api/v1/world/map`),
  state: () => get(`/api/v1/world/state`),
  agent: (id) => get(`/api/v1/agents/${id}`),
  streamURL: () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const host = new URL(BASE || location.href).host || location.host;
    const prefix = BASE.startsWith("http") ? new URL(BASE).host : host;
    return `${proto}://${prefix}/api/v1/events/stream`;
  },
};
