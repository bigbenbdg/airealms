"""Game rules: cooldowns, combat, XP, actions. All timing server-authoritative."""
import json
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

ACTION_DEFS = [
    {"name": "move", "description": "Travel to an adjacent location. On arrival you are told everyone there: all NPCs (names, roles, IDs) plus monster/loot/agent headcounts.", "cooldown_seconds": 10,
     "params": {"to": "string (location_id, must be an exit from current location)"}},
    {"name": "attack", "description": "Attack a monster or another agent present at your location.", "cooldown_seconds": 5,
     "params": {"target_id": "string (monster_id or agent_id present at your location)"}},
    {"name": "flee", "description": "Attempt to escape combat back to the previous location.", "cooldown_seconds": 5, "params": {}},
    {"name": "use_item", "description": "Consume or activate an item from your inventory.", "cooldown_seconds": 3,
     "params": {"item_id": "string"}},
    {"name": "equip_item", "description": "Equip a weapon/armor item you own.", "cooldown_seconds": 3,
     "params": {"item_id": "string"}},
    {"name": "pick_up", "description": "Pick up an item lying at your current location.", "cooldown_seconds": 2,
     "params": {"item_id": "string"}},
    {"name": "talk_to_npc", "description": "Speak to an NPC present at your location (shop, lore, quest-giver).", "cooldown_seconds": 2,
     "params": {"npc_id": "string"}},
    {"name": "buy_item", "description": "Buy an item from the merchant (Armorer Sella in Capital City). Must stand with her after talk_to_npc; item must meet your level.", "cooldown_seconds": 3,
     "params": {"npc_id": "string (merchant npc_id)", "item_id": "string"}},
    {"name": "sell_item", "description": "Sell a monster trophy to the merchant (Armorer Sella in Capital City). Must stand with her after talk_to_npc.", "cooldown_seconds": 2,
     "params": {"npc_id": "string (merchant npc_id)", "item_id": "string", "qty": "integer (optional, default 1)"}},
    {"name": "accept_quest", "description": "Accept a quest from its giver: must be at the giver NPC's location after talk_to_npc.", "cooldown_seconds": 2,
     "params": {"quest_id": "string"}},
    {"name": "turn_in_quest", "description": "Turn in a quest to its giver: must be at the giver's location, after talk_to_npc while holding the items (consumed).", "cooldown_seconds": 2,
     "params": {"quest_id": "string"}},
    {"name": "rest", "description": "Recover HP over time while stationary. Long cooldown.", "cooldown_seconds": 60, "params": {}},
    {"name": "say", "description": "Emit a public chat message visible to others at your location and in the event feed.", "cooldown_seconds": 5,
     "params": {"message": "string, max 200 chars"}},
    {"name": "scout", "description": "Gather full intel on an adjacent location without moving: danger, monsters, loot, NPCs, quests, players.", "cooldown_seconds": 5,
     "params": {"to": "string (location_id, must be an exit from current location)"}},
]
COOLDOWN_BY_ACTION = {a["name"]: a["cooldown_seconds"] for a in ACTION_DEFS}

# Required params per action — checked up front so clients get INVALID_PARAMS
# instead of a confusing downstream error (e.g. attack with no target).
REQUIRED_PARAMS = {
    "move": ["to"],
    "scout": ["to"],
    "attack": ["target_id"],
    "use_item": ["item_id"],
    "equip_item": ["item_id"],
    "pick_up": ["item_id"],
    "talk_to_npc": ["npc_id"],
    "buy_item": ["npc_id", "item_id"],
    "sell_item": ["npc_id", "item_id"],
    "accept_quest": ["quest_id"],
    "turn_in_quest": ["quest_id"],
    "say": ["message"],
}

# Village regeneration: +5 HP per completed action while in a town location.
VILLAGE_REGEN_HP = 5

# Monster respawn: smaller monsters come back faster.
# delay = base + max_hp * per_hp  →  rat (8 HP) ~85s, wolf (14) ~115s,
# bandit (16) ~125s, wraith (22) ~155s, troll (30) ~195s, drake (45) ~270s.
RESPAWN_BASE_SECONDS = 45
RESPAWN_PER_HP_SECONDS = 5


def respawn_delay_seconds(monster) -> int:
    return RESPAWN_BASE_SECONDS + (monster.max_hp or 0) * RESPAWN_PER_HP_SECONDS


def seconds_since(dt) -> float:
    if dt is None:
        return float("inf")
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds()


def respawn_due(db, location: str | None = None) -> int:
    """Revive monsters whose respawn timer elapsed. Returns count revived."""
    from .models import Monster
    q = db.query(Monster).filter(Monster.alive == False)  # noqa: E712
    if location is not None:
        q = q.filter(Monster.location == location)
    revived = 0
    for m in q.all():
        if seconds_since(m.died_at) >= respawn_delay_seconds(m):
            m.alive = True
            m.hp = m.max_hp
            m.died_at = None
            revived += 1
    if revived:
        db.commit()
    return revived

# --- rate limiting: 1 req/s sustained, burst 5 per key ---
_hits = defaultdict(deque)


def check_rate_limit(key: str):
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > 5:
        q.popleft()
    if len(q) >= 5:
        return False
    q.append(now)
    return True


# --- idempotency ---
_seen_keys = {}


def check_idempotency(key: str):
    if not key:
        return None
    return _seen_keys.get(key)


def store_idempotency(key: str, payload: dict):
    if key:
        _seen_keys[key] = payload


# --- helpers ---
def load_json(s, default):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default


def xp_for_level(level: int) -> int:
    return level * 200


def apply_xp(agent, amount: int):
    """Returns (leveled_up: bool)."""
    agent.xp += amount
    leveled = False
    while agent.xp >= xp_for_level(agent.level):
        agent.xp -= xp_for_level(agent.level)
        agent.level += 1
        agent.max_hp += 4
        agent.hp = agent.max_hp
        stats = load_json(agent.stats, {})
        stats["str"] = stats.get("str", 3) + 1
        agent.stats = json.dumps(stats)
        leveled = True
    return leveled


def player_attack_damage(agent) -> int:
    stats = load_json(agent.stats, {})
    inv = load_json(agent.inventory, [])
    bonus = sum(i.get("bonus", 0) for i in inv if i.get("equipped"))
    base = 3 + stats.get("str", 3) // 2 + bonus
    return max(1, base + random.randint(1, 6) - 2)


def player_defense(agent) -> int:
    """Total damage reduction from equipped armor (defense stat)."""
    inv = load_json(agent.inventory, [])
    return sum(i.get("defense", 0) for i in inv if i.get("equipped"))


def monster_attack_damage(monster) -> int:
    return max(1, monster.max_hp // 5 + random.randint(0, 3))


def set_cooldown(agent, action_name: str):
    secs = COOLDOWN_BY_ACTION.get(action_name, 5)
    agent.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=secs)
    return secs


def cooldown_remaining(agent) -> int:
    now = datetime.now(timezone.utc)
    cu = agent.cooldown_until
    if cu is None:
        return 0
    if cu.tzinfo is None:
        cu = cu.replace(tzinfo=timezone.utc)
    return max(0, int((cu - now).total_seconds()))


# --- WS fanout ---
class ConnectionManager:
    def __init__(self):
        self.active = []

    async def connect(self, ws):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, event: dict):
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
