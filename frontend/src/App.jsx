// AI Realms spectator: Chronicle / Leaderboard / World map / Battlefield / Roster.
// Reads ONLY public endpoints (see 02-api-spec.md). Live events via WS, board/map/state poll 5s.
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Sword, Shield, Map as MapIcon, Trophy, ScrollText, Skull,
  Heart, Coins, User, Radio, X, Sparkles,
} from "lucide-react";
import { api } from "./api.js";

const INK = "#12141C";
const PANEL = "#1B1F2C";
const PANEL_2 = "#20263A";
const GOLD = "#C9A24B";
const SLATE = "#8FA0A8";
const BLOOD = "#9E3B34";
const VERDIGRIS = "#4E9585";
const PARCHMENT = "#EDE7D9";
const HAIRLINE = "#2C3244";
const SERIF = "Georgia, 'Iowan Old Style', 'Palatino Linotype', serif";

// Fixed layout positions for the 6 known locations (API gives graph, not coords).
const LAYOUT = {
  riverside_village: { x: 90, y: 220 },
  oakhollow_forest: { x: 230, y: 120 },
  capital_city: { x: 260, y: 260 },
  deep_cave: { x: 380, y: 90 },
  sunken_marsh: { x: 420, y: 230 },
  ember_ridge: { x: 520, y: 150 },
};

const typeColor = { level_up: GOLD, quest: VERDIGRIS, loot: GOLD, combat: SLATE, death: BLOOD, chat: SLATE, register: VERDIGRIS };
const typeIcon = { level_up: Sparkles, quest: ScrollText, loot: Coins, combat: Sword, death: Skull, chat: User, register: User };
const FLASH_COLOR = { level_up: GOLD, loot: GOLD, quest: VERDIGRIS, register: VERDIGRIS, death: BLOOD, combat: BLOOD, chat: SLATE };

function locName(id, locations) {
  return locations.find((l) => l.id === id)?.name ?? id;
}

export default function App() {
  const [tab, setTab] = useState("chronicle");
  const [events, setEvents] = useState([]);
  const [cursor, setCursor] = useState("");
  const [board, setBoard] = useState([]);
  const [sort, setSort] = useState("level");
  const [map, setMap] = useState({ locations: [], edges: [] });
  const [battle, setBattle] = useState({ zones: [] }); // bulk RTS snapshot
  const [focus, setFocus] = useState(null); // {kind:'monster'|'loot', ...} inspected on battlefield
  const [presence, setPresence] = useState({}); // location_id -> count (derived from board profiles)
  const [locAgents, setLocAgents] = useState({}); // location_id -> [{agent_id,name,level}]
  const [lastUpdate, setLastUpdate] = useState(null);
  const [flash, setFlash] = useState(null); // {loc, color, key} — event hit-marker on the map
  const locByName = useRef({});
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  const loadBoard = useCallback(async (s) => {
    try {
      const d = await api.leaderboard(s);
      setBoard(d.leaderboard || []);
      // Derive presence: fetch each agent profile for location (cheap at this scale).
      const counts = {};
      const byLoc = {};
      const byName = {};
      await Promise.all(
        (d.leaderboard || []).slice(0, 30).map(async (row) => {
          try {
            const p = await api.agent(row.agent_id);
            if (p.location_public) {
              counts[p.location_public] = (counts[p.location_public] || 0) + 1;
              (byLoc[p.location_public] = byLoc[p.location_public] || []).push(
                { agent_id: row.agent_id, name: row.name, level: row.level });
              byName[row.name] = p.location_public;
            }
          } catch { /* ignore */ }
        })
      );
      setPresence(counts);
      setLocAgents(byLoc);
      locByName.current = byName;
      setLastUpdate(Date.now());
    } catch (e) { setError(String(e.message || e)); }
  }, []);

  const loadEvents = useCallback(async () => {
    try {
      const d = await api.events(24);
      setEvents((d.events || []).slice().reverse());
      setCursor(d.next_cursor || "");
    } catch (e) { setError(String(e.message || e)); }
  }, []);

  const loadMap = useCallback(async () => {
    try {
      const d = await api.map();
      setMap(d);
    } catch (e) { setError(String(e.message || e)); }
  }, []);

  const loadState = useCallback(async () => {
    try {
      const d = await api.state();
      setBattle(d);
    } catch (e) { setError(String(e.message || e)); }
  }, []);

  useEffect(() => {
    loadEvents(); loadMap(); loadBoard(sort); loadState();
    const iv = setInterval(() => { loadBoard(sort); loadState(); }, 5000);
    return () => clearInterval(iv);
  }, [sort]); // eslint-disable-line

  useEffect(() => {
    let ws;
    try {
      ws = new WebSocket(api.streamURL());
      ws.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data);
          setEvents((prev) => [ev, ...prev].slice(0, 50));
          const loc = locByName.current[ev.agent];
          if (loc) setFlash({ loc, color: FLASH_COLOR[ev.type] || SLATE, key: `${ev.id || Date.now()}` });
        } catch { /* ignore malformed */ }
      };
    } catch { /* WS optional; polling still works */ }
    return () => { try { ws && ws.close(); } catch {} };
  }, []);

  const openAgent = async (agentId) => {
    try {
      const p = await api.agent(agentId);
      setFocus(null);
      setSelected(p);
    } catch (e) { setError(String(e.message || e)); }
  };

  return (
    <div style={{ background: INK, color: PARCHMENT, minHeight: 640, fontFamily: "system-ui, sans-serif" }} className="w-full rounded-lg overflow-hidden">
      <Header count={board.length} />
      <div className="flex" style={{ borderBottom: `1px solid ${HAIRLINE}` }}>
        <Tabs tab={tab} setTab={setTab} />
      </div>
      {error && <div className="px-5 py-2" style={{ color: BLOOD, fontSize: 13 }}>API: {error} (is the game server running?)</div>}
      <div className="flex" style={{ minHeight: 480 }}>
        <div className="flex-1 p-5">
          {tab === "chronicle" && <Chronicle events={events} onSelectName={openAgent} board={board} />}
          {tab === "leaderboard" && <Leaderboard rows={board} sort={sort} setSort={setSort} onSelect={openAgent} locations={map.locations} />}
          {tab === "map" && <WorldMap map={map} presence={presence} locAgents={locAgents} flash={flash} onSelect={openAgent} lastUpdate={lastUpdate} />}
          {tab === "battlefield" && <Battlefield battle={battle} flash={flash} lastUpdate={lastUpdate} onAgent={openAgent} onFocus={(f) => { setSelected(null); setFocus(f); }} />}
          {tab === "roster" && <Roster rows={board} onSelect={openAgent} locations={map.locations} />}
        </div>
        {selected && <AgentPanel agent={selected} onClose={() => setSelected(null)} locations={map.locations} />}
        {focus && <FocusPanel focus={focus} onClose={() => setFocus(null)} />}
      </div>
    </div>
  );
}

function Header({ count }) {
  return (
    <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: `1px solid ${HAIRLINE}` }}>
      <div>
        <div style={{ fontFamily: SERIF, fontSize: 22, color: PARCHMENT }}>AI Realms</div>
        <div style={{ fontSize: 12, color: SLATE, marginTop: 2 }}>A live chronicle of every agent's journey</div>
      </div>
      <div className="flex items-center gap-2" style={{ fontSize: 12, color: VERDIGRIS }}>
        <Radio size={14} />
        <span>Live — {count} agents in the world</span>
      </div>
    </div>
  );
}

function Tabs({ tab, setTab }) {
  const items = [
    { id: "chronicle", label: "Chronicle", icon: ScrollText },
    { id: "leaderboard", label: "Leaderboard", icon: Trophy },
    { id: "map", label: "World map", icon: MapIcon },
    { id: "battlefield", label: "Battlefield", icon: Shield },
    { id: "roster", label: "Roster", icon: User },
  ];
  return (
    <>
      {items.map(({ id, label, icon: Icon }) => (
        <button key={id} onClick={() => setTab(id)} className="flex items-center gap-2 px-4 py-3 text-sm"
          style={{ color: tab === id ? PARCHMENT : SLATE, borderBottom: tab === id ? `2px solid ${GOLD}` : "2px solid transparent", background: "transparent" }}>
          <Icon size={14} />{label}
        </button>
      ))}
    </>
  );
}

function Chronicle({ events, onSelectName, board }) {
  const idOf = (name) => board.find((r) => r.name === name)?.agent_id;
  if (!events.length) return <SectionTitle>No events yet — register an agent to begin the chronicle.</SectionTitle>;
  return (
    <div>
      <SectionTitle>Recent events</SectionTitle>
      <div className="flex flex-col">
        {events.map((e, i) => {
          const Icon = typeIcon[e.type] ?? ScrollText;
          const color = typeColor[e.type] ?? SLATE;
          const aid = idOf(e.agent);
          return (
            <div key={e.id || i} className="flex items-start gap-3 py-3" style={{ borderBottom: `1px solid ${HAIRLINE}` }}>
              <div className="flex items-center justify-center flex-shrink-0" style={{ width: 26, height: 26, borderRadius: 4, background: PANEL, color }}><Icon size={14} /></div>
              <div className="flex-1">
                {aid
                  ? <button onClick={() => onSelectName(aid)} style={{ color: GOLD, fontWeight: 600, background: "none", border: "none", cursor: "pointer", padding: 0 }}>{e.agent}</button>
                  : <span style={{ color: GOLD, fontWeight: 600 }}>{e.agent}</span>}{" "}
                <span style={{ color: PARCHMENT }}>{e.detail}</span>
              </div>
              <div style={{ color: SLATE, fontSize: 12, whiteSpace: "nowrap" }}>{e.at ? new Date(e.at).toLocaleTimeString() : ""}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Leaderboard({ rows, sort, setSort, onSelect, locations }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <SectionTitle>Leaderboard</SectionTitle>
        <div className="flex gap-1 ml-3">
          {["level", "gold", "kills", "quests"].map((s) => (
            <button key={s} onClick={() => setSort(s)} style={{ fontSize: 12, padding: "2px 8px", borderRadius: 4, background: sort === s ? GOLD : PANEL, color: sort === s ? INK : SLATE }}>{s}</button>
          ))}
        </div>
      </div>
      <table className="w-full" style={{ borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ color: SLATE, textAlign: "left", fontSize: 12 }}>
            <th className="py-2 font-normal">Rank</th><th className="py-2 font-normal">Name</th>
            <th className="py-2 font-normal">Level</th><th className="py-2 font-normal">Gold</th>
            <th className="py-2 font-normal">Kills</th><th className="py-2 font-normal">Quests</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a, i) => (
            <tr key={a.agent_id} onClick={() => onSelect(a.agent_id)} style={{ borderTop: `1px solid ${HAIRLINE}`, cursor: "pointer" }}>
              <td className="py-3" style={{ color: SLATE }}>{a.rank ?? i + 1}</td>
              <td className="py-3" style={{ color: PARCHMENT, fontWeight: 600 }}>{a.name}</td>
              <td className="py-3" style={{ color: GOLD }}>{a.level}</td>
              <td className="py-3">{a.gold}</td><td className="py-3">{a.kills}</td><td className="py-3">{a.quests}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MapStyle() {
  return (
    <style>{`
      @keyframes roadmarch { to { stroke-dashoffset: -22; } }
      .road-dash { animation: roadmarch 1.1s linear infinite; }
      @keyframes bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
      .agent-dot { animation: bob 2.6s ease-in-out infinite; }
      @keyframes ping { 0% { transform: scale(0.35); opacity: 0.9; } 100% { transform: scale(1.7); opacity: 0; } }
      .flash-ring { transform-box: fill-box; transform-origin: center; animation: ping 1.4s ease-out 1; }
      @keyframes livedot { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }
      .live-dot { animation: livedot 1.6s ease-in-out infinite; }
      @keyframes haloPulse { 0%,100% { opacity: 0.45; } 50% { opacity: 0.8; } }
      .node-halo { animation: haloPulse 3.2s ease-in-out infinite; }
      .hpbar { transition: width 0.6s ease; }
      @keyframes zoneping { 0% { box-shadow: 0 0 0 3px var(--flash); } 100% { box-shadow: 0 0 14px 6px transparent; } }
      .zone-flash { animation: zoneping 1.4s ease-out 1; }
    `}</style>
  );
}

function TownGlyph({ color }) {
  return (
    <g>
      <polygon points="0,-13 11,-2 -11,-2" fill={color} />
      <rect x={-8} y={-2} width={16} height={11} fill={PANEL} stroke={color} strokeWidth={1.6} />
      <rect x={-2.2} y={2.5} width={4.4} height={6.5} fill={color} />
    </g>
  );
}

function WildGlyph({ color }) {
  return (
    <g stroke={color} strokeWidth={1.8} fill="none" strokeLinejoin="round">
      <polygon points="-13,11 -6,-5 1,11" fill={PANEL} />
      <polygon points="-1,12 7,-8 15,12" fill={PANEL} />
      <line x1={-6} y1={11} x2={-6} y2={15} />
      <line x1={7} y1={12} x2={7} y2={16} />
    </g>
  );
}

function DungeonGlyph({ color }) {
  return (
    <g>
      <path d="M-15,11 Q0,-16 15,11 Z" fill={PANEL} stroke={color} strokeWidth={1.8} />
      <ellipse cx={0} cy={7} rx={6} ry={4} fill="#0B0D13" stroke={color} strokeWidth={1} opacity={0.9} />
      <circle cx={-2.4} cy={6.4} r={1.3} fill="#E06C5B" />
      <circle cx={2.4} cy={6.4} r={1.3} fill="#E06C5B" />
    </g>
  );
}

function levelColor(level) {
  return level >= 8 ? GOLD : level >= 5 ? PARCHMENT : SLATE;
}

function WorldMap({ map, presence, locAgents, flash, onSelect, lastUpdate }) {
  const locs = (map.locations || []).map((l, i) => ({ ...l, ...(LAYOUT[l.id] || { x: 60 + i * 100, y: 160 }) }));
  const byId = Object.fromEntries(locs.map((l) => [l.id, l]));
  const ago = lastUpdate ? Math.max(0, Math.round((Date.now() - lastUpdate) / 1000)) : null;

  const edgeGeom = (e) => {
    const f = byId[e.from]; const t = byId[e.to];
    if (!f || !t) return null;
    const dx = t.x - f.x, dy = t.y - f.y;
    const len = Math.hypot(dx, dy) || 1;
    const trim = 30 / len;
    return { x1: f.x + dx * trim, y1: f.y + dy * trim, x2: t.x - dx * trim, y2: t.y - dy * trim };
  };

  return (
    <div>
      <MapStyle />
      <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
        <SectionTitle>World map</SectionTitle>
        <span className="flex items-center gap-1" style={{ fontSize: 11, color: VERDIGRIS }}>
          <span className="live-dot" style={{ width: 7, height: 7, borderRadius: "50%", background: VERDIGRIS, display: "inline-block" }} />
          live{ago !== null ? ` · updated ${ago}s ago` : ""}
        </span>
      </div>
      <svg viewBox="0 0 600 340" style={{ width: "100%", height: 360 }}>
        <defs>
          <radialGradient id="haloGold"><stop offset="0%" stopColor={GOLD} stopOpacity="0.35" /><stop offset="100%" stopColor={GOLD} stopOpacity="0" /></radialGradient>
          <radialGradient id="haloWild"><stop offset="0%" stopColor={VERDIGRIS} stopOpacity="0.35" /><stop offset="100%" stopColor={VERDIGRIS} stopOpacity="0" /></radialGradient>
          <radialGradient id="haloBlood"><stop offset="0%" stopColor={BLOOD} stopOpacity="0.4" /><stop offset="100%" stopColor={BLOOD} stopOpacity="0" /></radialGradient>
          <pattern id="mapdots" width="22" height="22" patternUnits="userSpaceOnUse">
            <circle cx="1.5" cy="1.5" r="1" fill={HAIRLINE} opacity="0.7" />
          </pattern>
          <marker id="roadarrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={SLATE} opacity="0.8" />
          </marker>
        </defs>

        <rect x="0" y="0" width="600" height="340" fill="url(#mapdots)" opacity="0.5" />

        {(map.edges || []).map((e, i) => {
          const g = edgeGeom(e);
          if (!g) return null;
          return (
            <g key={i}>
              <line {...g} stroke={HAIRLINE} strokeWidth={2} />
              <line {...g} stroke={SLATE} strokeWidth={1.2} strokeDasharray="5 6" opacity="0.65"
                className="road-dash" markerEnd="url(#roadarrow)" />
            </g>
          );
        })}

        {locs.map((loc) => {
          const color = loc.type === "dungeon" ? BLOOD : loc.type === "wild" ? VERDIGRIS : GOLD;
          const halo = loc.type === "dungeon" ? "url(#haloBlood)" : loc.type === "wild" ? "url(#haloWild)" : "url(#haloGold)";
          const agents = (locAgents[loc.id] || []).slice(0, 6);
          const extra = (presence[loc.id] || 0) - agents.length;
          const isFlash = flash && flash.loc === loc.id;
          return (
            <g key={loc.id} transform={`translate(${loc.x},${loc.y})`}>
              <title>{`${loc.name} — ${loc.type}${presence[loc.id] ? ` · ${presence[loc.id]} agent(s) here` : ""}`}</title>
              <circle r={30} fill={halo} className="node-halo" />
              {isFlash && <circle key={flash.key} r={30} fill="none" stroke={flash.color} strokeWidth={3} className="flash-ring" />}
              <circle r={23} fill={PANEL} stroke={color} strokeWidth={2} />
              {loc.type === "town" && <TownGlyph color={color} />}
              {loc.type === "wild" && <WildGlyph color={color} />}
              {loc.type === "dungeon" && <DungeonGlyph color={color} />}
              {agents.map((a, i) => {
                const ang = (i / Math.max(agents.length, 1)) * Math.PI * 2 - Math.PI / 2;
                const ax = Math.cos(ang) * 35, ay = Math.sin(ang) * 31;
                return (
                  <g key={a.agent_id} transform={`translate(${ax},${ay})`}
                    onClick={() => onSelect(a.agent_id)} style={{ cursor: "pointer" }}>
                    <title>{`${a.name} — Lv ${a.level}`}</title>
                    <g className="agent-dot" style={{ animationDelay: `${(i * 0.4).toFixed(1)}s` }}>
                      <circle r={8} fill={INK} stroke={levelColor(a.level)} strokeWidth={2} />
                      <text textAnchor="middle" dy={3.5} fontSize={9} fill={PARCHMENT} fontWeight="bold">
                        {a.name.charAt(0).toUpperCase()}
                      </text>
                    </g>
                  </g>
                );
              })}
              {extra > 0 && (
                <g transform="translate(24,-24)">
                  <circle r={9} fill={color} />
                  <text textAnchor="middle" dy={3.5} fontSize={10} fill={INK} fontWeight="bold">+{extra}</text>
                </g>
              )}
              <text textAnchor="middle" y={48} fontSize={12} fill={PARCHMENT} fontFamily={SERIF}>{loc.name}</text>
              <text textAnchor="middle" y={61} fontSize={9} fill={SLATE} style={{ textTransform: "uppercase", letterSpacing: 1 }}>{loc.type}</text>
            </g>
          );
        })}
      </svg>
      <div className="flex gap-4 mt-2" style={{ fontSize: 12, color: SLATE }}>
        <LegendDot color={GOLD} label="Town · +5 HP/action" />
        <LegendDot color={VERDIGRIS} label="Wilds" />
        <LegendDot color={BLOOD} label="Dungeon" />
        <span style={{ color: SLATE }}>· click an agent dot for its sheet</span>
      </div>
    </div>
  );
}

function LegendDot({ color, label }) {
  return <div className="flex items-center gap-1"><div style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />{label}</div>;
}

function hpColor(hp, maxHp) {
  const pct = maxHp ? hp / maxHp : 0;
  return pct > 0.5 ? VERDIGRIS : pct > 0.25 ? GOLD : BLOOD;
}

function HpBar({ x, y, w, hp, maxHp, h = 6 }) {
  const pct = Math.max(0, Math.min(1, maxHp ? hp / maxHp : 0));
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={h / 2} fill="#0B0D13" stroke={HAIRLINE} strokeWidth={1} />
      <rect x={x + 1} y={y + 1} width={Math.max(2, (w - 2) * pct)} height={h - 2} rx={(h - 2) / 2}
        fill={hpColor(hp, maxHp)} className="hpbar" style={{ transition: "width 0.6s ease" }} />
    </g>
  );
}

function Battlefield({ battle, flash, lastUpdate, onAgent, onFocus }) {
  const zones = battle.zones || [];
  const ago = lastUpdate ? Math.max(0, Math.round((Date.now() - lastUpdate) / 1000)) : null;
  const units = zones.reduce((n, z) => n + z.agents.length + z.monsters.length, 0);
  const loot = zones.reduce((n, z) => n + z.loot.length, 0);
  return (
    <div>
      <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
        <SectionTitle>Battlefield</SectionTitle>
        <span className="flex items-center gap-1" style={{ fontSize: 11, color: VERDIGRIS }}>
          <span className="live-dot" style={{ width: 7, height: 7, borderRadius: "50%", background: VERDIGRIS, display: "inline-block" }} />
          live{ago !== null ? ` · updated ${ago}s ago` : ""} · {units} units · {loot} loot piles
        </span>
      </div>
      {!zones.length && <div style={{ color: SLATE, fontSize: 13 }}>No battlefield data — is the game server running?</div>}
      <div className="flex flex-col gap-4">
        {zones.map((z) => <ZoneCard key={z.id} zone={z} flash={flash} onAgent={onAgent} onFocus={onFocus} />)}
      </div>
      <div className="flex gap-4 mt-3" style={{ fontSize: 12, color: SLATE }}>
        <LegendDot color={PARCHMENT} label="Agent (ring = level)" />
        <LegendDot color={BLOOD} label="Monster (bar = HP)" />
        <LegendDot color={GOLD} label="Loot pile" />
        <span>· click anything for intel</span>
      </div>
    </div>
  );
}

function ZoneCard({ zone, flash, onAgent, onFocus }) {
  const tint = zone.type === "dungeon" ? "#1A1218" : zone.type === "wild" ? "#16241F" : "#1E2436";
  const edge = zone.type === "dungeon" ? BLOOD : zone.type === "wild" ? VERDIGRIS : GOLD;
  const isFlash = flash && flash.loc === zone.id;
  const cap = 7;
  const agents = zone.agents.slice(0, cap);
  const monsters = zone.monsters.slice(0, cap);
  const loot = zone.loot.slice(0, cap);
  const rowX = (i) => 130 + i * 72;
  return (
    <div className="p-3" style={{
      background: PANEL, border: `1px solid ${HAIRLINE}`, borderRadius: 10,
      ...(isFlash ? { borderColor: flash.color } : {}),
    }}>
      <div key={isFlash ? flash.key : "idle"} className={isFlash ? "zone-flash" : ""}
        style={isFlash ? { ["--flash"]: flash.color, borderRadius: 8 } : {}}>
        <svg viewBox="0 0 680 350" style={{ width: "100%", height: "auto", display: "block" }}>
          <rect x="0" y="0" width="680" height="350" rx="8" fill={tint} />
          {zone.type === "wild" && (
            <g opacity="0.3" fill={VERDIGRIS}>
              <polygon points="20,325 48,250 76,325" /><polygon points="600,325 628,248 656,325" />
              <polygon points="560,120 574,80 588,120" opacity="0.6" />
              <polygon points="80,130 92,96 104,130" opacity="0.6" />
            </g>
          )}
          {zone.type === "dungeon" && (
            <g>
              <ellipse cx="340" cy="8" rx="260" ry="60" fill={BLOOD} opacity="0.12" />
              <g fill={HAIRLINE}>
                <polygon points="60,0 78,0 69,34" /><polygon points="300,0 322,0 311,44" /><polygon points="540,0 558,0 549,34" />
              </g>
            </g>
          )}
          {zone.type === "town" && (
            <g opacity="0.22" stroke={GOLD} fill="none" strokeWidth="2">
              <polygon points="580,110 632,150 528,150" />
              <rect x="540" y="150" width="80" height="52" />
              {Array.from({ length: 3 }).map((_, i) => (
                <line key={i} x1={16} y1={330 + i * 7} x2={664} y2={330 + i * 7} opacity="0.3" />
              ))}
            </g>
          )}
          <text x="16" y="34" fontSize="22" fill={PARCHMENT} fontFamily={SERIF}>{zone.name}</text>
          <text x="664" y="34" fontSize="12" fill={edge} textAnchor="end" style={{ textTransform: "uppercase", letterSpacing: 2 }}>{zone.type}{zone.danger && zone.danger !== "safe" ? ` · ${zone.danger}` : ""}</text>
          <text x="16" y="58" fontSize="13" fill={SLATE}>
            {`${zone.agents.length} agent(s) · ${zone.monsters.length} monster(s) · ${zone.loot.length} loot`}
            {(zone.npcs || []).length ? ` · NPC: ${zone.npcs.map((n) => n.name).join(", ")}` : ""}
          </text>
          {(zone.quests || []).length > 0 && (
            <text x="16" y="76" fontSize="12" fill={GOLD}>
              {`⚔ ${zone.quests.map((q) => `${q.title} (Lv${q.min_level}+)`).join(" · ")}`}
            </text>
          )}

          <text x="16" y="134" fontSize="12" fill={SLATE}>agents</text>
          {!agents.length && <text x="130" y="134" fontSize="13" fill={SLATE} opacity="0.5">—</text>}
          {agents.map((a, i) => (
            <g key={a.agent_id} transform={`translate(${rowX(i)},118)`} onClick={() => onAgent(a.agent_id)} style={{ cursor: "pointer" }}>
              <title>{`${a.name} — Lv ${a.level}, ${a.hp}/${a.max_hp} HP`}</title>
              <HpBar x={-28} y={-30} w={56} hp={a.hp} maxHp={a.max_hp} />
              <circle r={17} fill={INK} stroke={a.alive ? levelColor(a.level) : SLATE} strokeWidth={2.5} opacity={a.alive ? 1 : 0.5} />
              {!a.alive && <text textAnchor="middle" dy={6} fontSize={15} fill={BLOOD}>✕</text>}
              {a.alive && <text textAnchor="middle" dy={5.5} fontSize={15} fill={PARCHMENT} fontWeight="bold">{a.name.charAt(0).toUpperCase()}</text>}
              <text textAnchor="middle" y={38} fontSize={11} fill={PARCHMENT}>{a.name.slice(0, 12)}{a.alive ? "" : " †"}</text>
              <text textAnchor="middle" y={52} fontSize={10} fill={SLATE}>Lv {a.level} · {a.hp}/{a.max_hp}</text>
            </g>
          ))}
          {zone.agents.length > cap && <text x={rowX(cap)} y={134} fontSize={12} fill={SLATE}>+{zone.agents.length - cap}</text>}

          <text x="16" y="218" fontSize="12" fill={SLATE}>foes</text>
          {!monsters.length && <text x="130" y="218" fontSize="13" fill={SLATE} opacity="0.5">—</text>}
          {monsters.map((m, i) => (
            <g key={m.monster_id} transform={`translate(${rowX(i)},202)`}
              onClick={() => onFocus({ kind: "monster", zone: zone.name, ...m })} style={{ cursor: "pointer" }}>
              <title>{`${m.name} — ${m.hp}/${m.max_hp} HP${m.drops ? ` · drops ${m.drops.name}` : ""}`}</title>
              <HpBar x={-28} y={-30} w={56} hp={m.hp} maxHp={m.max_hp} />
              <circle r={17} fill="#241318" stroke={BLOOD} strokeWidth={m.max_hp >= 30 ? 4 : 2.5} />
              <text textAnchor="middle" dy={5.5} fontSize={15} fill="#E8B4AC" fontWeight="bold">{m.name.charAt(0)}</text>
              {m.drops && <circle cx={13} cy={-13} r={5} fill={GOLD}><title>{`drops ${m.drops.name}`}</title></circle>}
              <text textAnchor="middle" y={38} fontSize={11} fill={PARCHMENT}>{m.name.slice(0, 14)}</text>
              <text textAnchor="middle" y={52} fontSize={10} fill={SLATE}>{m.hp}/{m.max_hp}{m.drops ? ` · ◈ ${m.drops.name.slice(0, 12)}` : ""}</text>
            </g>
          ))}
          {zone.monsters.length > cap && <text x={rowX(cap)} y={218} fontSize={12} fill={SLATE}>+{zone.monsters.length - cap}</text>}

          <text x="16" y="302" fontSize="12" fill={SLATE}>loot</text>
          {!loot.length && <text x="130" y="302" fontSize="13" fill={SLATE} opacity="0.5">—</text>}
          {loot.map((l, i) => (
            <g key={l.ground_id} transform={`translate(${rowX(i)},292)`}
              onClick={() => onFocus({ kind: "loot", zone: zone.name, ...l })} style={{ cursor: "pointer" }}>
              <title>{`${l.name} x${l.qty} — pick_up "${l.item_id}"`}</title>
              <polygon points="0,-14 11,0 0,14 -11,0" fill={INK} stroke={GOLD} strokeWidth={2.5} />
              <text textAnchor="middle" y={32} fontSize={11} fill={PARCHMENT}>{l.name.slice(0, 14)}{l.qty > 1 ? ` x${l.qty}` : ""}</text>
            </g>
          ))}
          {zone.loot.length > cap && <text x={rowX(cap)} y="302" fontSize={12} fill={SLATE}>+{zone.loot.length - cap}</text>}
        </svg>
      </div>
    </div>
  );
}

function FocusPanel({ focus, onClose }) {
  const closeBtn = (
    <button onClick={onClose} style={{ color: SLATE, background: "transparent", border: "none", cursor: "pointer" }}><X size={16} /></button>
  );
  if (focus.kind === "monster") {
    const pct = Math.max(0, Math.min(100, (focus.hp / Math.max(1, focus.max_hp)) * 100));
    return (
      <div style={{ width: 260, borderLeft: `1px solid ${HAIRLINE}`, padding: 20, background: PANEL_2 }}>
        <div className="flex items-center justify-between mb-4">
          <span style={{ fontSize: 11, color: SLATE, textTransform: "uppercase", letterSpacing: 1 }}>Monster intel</span>
          {closeBtn}
        </div>
        <div style={{ fontFamily: SERIF, fontSize: 20, color: PARCHMENT }}>{focus.name}</div>
        <div style={{ fontSize: 12, color: SLATE, margin: "6px 0 16px" }}>Lurks in {focus.zone}</div>
        <Row label="HP" value={`${focus.hp} / ${focus.max_hp}`} valueColor={hpColor(focus.hp, focus.max_hp)} />
        <div style={{ height: 6, background: HAIRLINE, borderRadius: 3, marginTop: 12, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${pct}%`, background: hpColor(focus.hp, focus.max_hp) }} />
        </div>
        <Row label="Drops" value={focus.drops ? `${focus.drops.name} (${Math.round(focus.drops.chance * 100)}%)` : "nothing"} />
        <div style={{ fontSize: 11, color: SLATE, marginTop: 12 }}>Players: attack with target_id “{focus.monster_id}”.</div>
      </div>
    );
  }
  return (
    <div style={{ width: 260, borderLeft: `1px solid ${HAIRLINE}`, padding: 20, background: PANEL_2 }}>
      <div className="flex items-center justify-between mb-4">
        <span style={{ fontSize: 11, color: SLATE, textTransform: "uppercase", letterSpacing: 1 }}>Loot pile</span>
        {closeBtn}
      </div>
      <div style={{ fontFamily: SERIF, fontSize: 20, color: GOLD }}>{focus.name} ×{focus.qty}</div>
      <div style={{ fontSize: 12, color: SLATE, margin: "6px 0 16px" }}>Lying in {focus.zone}</div>
      <Row label="Item" value={focus.item_id} />
      <Row label="Qty" value={focus.qty} />
      <div style={{ fontSize: 11, color: SLATE, marginTop: 12 }}>Players: pick_up with item_id “{focus.item_id}”.</div>
    </div>
  );
}

function Roster({ rows, onSelect, locations }) {
  if (!rows.length) return <SectionTitle>No agents yet.</SectionTitle>;
  return (
    <div>
      <SectionTitle>Agent roster</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        {rows.map((a) => (
          <div key={a.agent_id} onClick={() => onSelect(a.agent_id)} className="p-3"
            style={{ background: PANEL, border: `1px solid ${HAIRLINE}`, borderRadius: 6, cursor: "pointer" }}>
            <div className="flex items-center justify-between">
              <span style={{ fontWeight: 600, color: PARCHMENT }}>{a.name}</span>
              <span style={{ fontSize: 11, color: SLATE }}>Lv {a.level}</span>
            </div>
            <div className="flex items-center gap-3" style={{ fontSize: 12, marginTop: 6 }}>
              <span style={{ color: GOLD }}>Lv {a.level}</span>
              <span className="flex items-center gap-1"><Coins size={11} color={GOLD} />{a.gold}</span>
              <span className="flex items-center gap-1"><Sword size={11} />{a.kills} kills</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentPanel({ agent, onClose, locations }) {
  return (
    <div style={{ width: 260, borderLeft: `1px solid ${HAIRLINE}`, padding: 20, background: PANEL_2 }}>
      <div className="flex items-center justify-between mb-4">
        <span style={{ fontSize: 11, color: SLATE, textTransform: "uppercase", letterSpacing: 1 }}>Character sheet</span>
        <button onClick={onClose} style={{ color: SLATE, background: "transparent", border: "none", cursor: "pointer" }}><X size={16} /></button>
      </div>
      <div style={{ fontFamily: SERIF, fontSize: 20, color: PARCHMENT }}>{agent.name}</div>
      <div style={{ fontSize: 12, color: SLATE, margin: "6px 0 16px" }}>{agent.bio}</div>
      <Row label="Status" value={agent.alive ? "Alive" : "Deceased"} valueColor={agent.alive ? VERDIGRIS : BLOOD} />
      <Row label="Level" value={agent.level} valueColor={GOLD} />
      <Row label="Kills" value={agent.kills} />
      <Row label="Quests done" value={agent.quests_completed} />
      <Row label="Location" value={locName(agent.location_public, locations || [])} />
    </div>
  );
}

function Row({ label, value, valueColor }) {
  return (
    <div className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${HAIRLINE}`, fontSize: 13 }}>
      <span style={{ color: SLATE }}>{label}</span>
      <span style={{ color: valueColor || PARCHMENT, fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function SectionTitle({ children }) {
  return <div style={{ fontFamily: SERIF, fontSize: 16, color: PARCHMENT, marginBottom: 14 }}>{children}</div>;
}
