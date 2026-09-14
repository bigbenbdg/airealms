"""Seed world: 6 locations (matches prototype), NPCs, monsters, quests, shop items."""
import json
from .models import Monster

LOCATIONS = [
    {"id": "riverside_village", "name": "Riverside Village", "type": "town",
     "description": "A modest village on the river. A blacksmith and an inn face the square."},
    {"id": "oakhollow_forest", "name": "Oakhollow Forest", "type": "wild",
     "description": "Tall oaks drip with moss. Wolves prowl between the trees."},
    {"id": "capital_city", "name": "Capital City", "type": "town",
     "description": "The bustling capital. Merchants shout, guards patrol, quests abound."},
    {"id": "deep_cave", "name": "Deep Cave", "type": "dungeon",
     "description": "A dark cave mouth. Something large breathes within."},
    {"id": "sunken_marsh", "name": "Sunken Marsh", "type": "wild",
     "description": "Knee-deep black water. Will-o'-wisps drift over the reeds."},
    {"id": "ember_ridge", "name": "Ember Ridge", "type": "dungeon",
     "description": "Volcanic rock glows faintly. The end-game hunting ground."},
]

EDGES = [
    {"from": "riverside_village", "to": "oakhollow_forest", "direction": "north"},
    {"from": "riverside_village", "to": "capital_city", "direction": "east"},
    {"from": "oakhollow_forest", "to": "deep_cave", "direction": "north"},
    {"from": "capital_city", "to": "sunken_marsh", "direction": "south"},
    {"from": "sunken_marsh", "to": "ember_ridge", "direction": "east"},
    {"from": "deep_cave", "to": "ember_ridge", "direction": "east"},
]

NPCS = [
    {"npc_id": "npc_blacksmith", "name": "Old Toran", "location": "riverside_village",
     "can_trade": False, "has_quest": True,
     "dialogue": "Giant rats nest in Oakhollow Forest and chew through my stock. Bring me 3 Rat Pelts."},
    {"npc_id": "npc_innkeeper", "name": "Mira the Innkeep", "location": "riverside_village",
     "can_trade": False, "has_quest": False,
     "dialogue": "Rest up, traveler. The forest is not kind to the wounded."},
    {"npc_id": "npc_captain", "name": "Captain Voss", "location": "capital_city",
     "can_trade": False, "has_quest": True,
     "dialogue": "Trolls in the Deep Cave threaten our trade. Bring me 2 Troll Hides for the city!"},
    {"npc_id": "npc_hermit", "name": "Marsh Hermit", "location": "sunken_marsh",
     "can_trade": False, "has_quest": True,
     "dialogue": "The marsh took my lantern. Bring me 2 Wraith Essences and I'll light your way."},
    {"npc_id": "npc_scout", "name": "Scout Liora", "location": "oakhollow_forest",
     "can_trade": False, "has_quest": True,
     "dialogue": "Wolves grow bold and stalk the road. Bring me 3 Wolf Pelts to thin their pride."},
    {"npc_id": "npc_merchant", "name": "Merchant Pella", "location": "capital_city",
     "can_trade": False, "has_quest": True,
     "dialogue": "Bandits rob my caravans on the capital road. Bring me 2 Bandit Daggers as proof."},
    {"npc_id": "npc_warden", "name": "Warden Cassia", "location": "ember_ridge",
     "can_trade": False, "has_quest": True,
     "dialogue": "Only proven slayers need apply: bring me a Drake Scale and the ridge is yours."},
    {"npc_id": "npc_armorer_sella", "name": "Armorer Sella", "location": "capital_city",
     "can_trade": True, "has_quest": False,
     "dialogue": "Blades, plate, and potions — tiered for your level. Sell me your monster trophies, too."},
]

# The one NPC allowed to trade. All buy_item/sell_item calls must name her.
MERCHANT_ID = "npc_armorer_sella"

QUESTS = {
    # Item turn-in chain tuned so completing everything carries an agent to ~level 5.
    # xp_for_level = level * 200, so L1 needs 200 total, L1->L5 needs 2000.
    # Each quest consumes the listed items on turn-in (drops from the source
    # monster, plus occasional ground loot). Drop chances live in MONSTER_DROPS.
    "q_ratcatcher": {"title": "The Ratcatcher's Request", "kind": "collect",
                     "item_id": "itm_rat_pelt", "item_name": "Rat Pelt", "count": 3,
                     "xp": 90, "gold": 45,
                     "min_level": 1, "giver": "npc_blacksmith"},
    "q_wolfpack": {"title": "Thin the Pack", "kind": "collect",
                   "item_id": "itm_wolf_pelt", "item_name": "Wolf Pelt", "count": 3,
                   "xp": 150, "gold": 80,
                   "min_level": 2, "giver": "npc_scout"},
    "q_bandit_toll": {"title": "The Bandit Toll", "kind": "collect",
                      "item_id": "itm_bandit_dagger", "item_name": "Bandit Dagger", "count": 2,
                      "xp": 160, "gold": 100,
                      "min_level": 2, "giver": "npc_merchant"},
    "q_trollbane": {"title": "Trolls of the Deep Cave", "kind": "collect",
                    "item_id": "itm_troll_hide", "item_name": "Troll Hide", "count": 2,
                    "xp": 220, "gold": 150,
                    "min_level": 3, "giver": "npc_captain"},
    "q_marshlight": {"title": "Light in the Marsh", "kind": "collect",
                     "item_id": "itm_wraith_essence", "item_name": "Wraith Essence", "count": 2,
                     "xp": 180, "gold": 120,
                     "min_level": 3, "giver": "npc_hermit"},
    "q_drakescale": {"title": "Scale of Embers", "kind": "collect",
                     "item_id": "itm_drake_scale", "item_name": "Drake Scale", "count": 1,
                     "xp": 400, "gold": 300,
                     "min_level": 5, "giver": "npc_warden"},
}

# Legacy general-store list (kept for backwards compat; no NPC sells it anymore).
# All commerce is exclusive to Armorer Sella — see ARMORER_STOCK / MERCHANT_BUYBACK.
SHOP = [
    {"item_id": "itm_healing_potion", "name": "Healing Potion", "price": 15, "heal": 12},
    {"item_id": "itm_iron_sword", "name": "Iron Sword", "price": 80, "bonus": 3},
    {"item_id": "itm_leather_armor", "name": "Leather Armor", "price": 60, "max_hp_bonus": 5},
]

# Armorer Sella's exclusive stock, tiered by minimum level band:
# T1 (Lv 1-2, cheap), T2 (Lv 3-4, mid), T3 (Lv 5+, best).
# Weapons carry bonus (+ATK), armors carry defense (+DEF damage reduction),
# potions carry heal. Bonus and price rise monotonically with tier.
ARMORER_STOCK = [
    # --- T1: levels 1-2 ---
    {"item_id": "itm_short_sword", "name": "Short Sword", "kind": "weapon",
     "price": 60, "min_level": 1, "bonus": 2},
    {"item_id": "itm_iron_sword", "name": "Iron Sword", "kind": "weapon",
     "price": 90, "min_level": 2, "bonus": 3},
    {"item_id": "itm_cloth_garb", "name": "Cloth Garb", "kind": "armor",
     "price": 50, "min_level": 1, "defense": 1},
    {"item_id": "itm_leather_armor", "name": "Leather Armor", "kind": "armor",
     "price": 80, "min_level": 2, "defense": 2},
    {"item_id": "itm_healing_potion", "name": "Healing Potion", "kind": "potion",
     "price": 15, "min_level": 1, "heal": 12},
    # --- T2: levels 3-4 ---
    {"item_id": "itm_knight_blade", "name": "Knight Blade", "kind": "weapon",
     "price": 180, "min_level": 3, "bonus": 5},
    {"item_id": "itm_rune_sword", "name": "Rune Sword", "kind": "weapon",
     "price": 250, "min_level": 4, "bonus": 6},
    {"item_id": "itm_chainmail", "name": "Chainmail", "kind": "armor",
     "price": 150, "min_level": 3, "defense": 4},
    {"item_id": "itm_plate_armor", "name": "Plate Armor", "kind": "armor",
     "price": 220, "min_level": 4, "defense": 5},
    {"item_id": "itm_greater_potion", "name": "Greater Potion", "kind": "potion",
     "price": 40, "min_level": 3, "heal": 25},
    # --- T3: level 5+ ---
    {"item_id": "itm_dragonslayer", "name": "Dragonslayer", "kind": "weapon",
     "price": 400, "min_level": 5, "bonus": 9},
    {"item_id": "itm_ember_greatsword", "name": "Ember Greatsword", "kind": "weapon",
     "price": 550, "min_level": 5, "bonus": 11},
    {"item_id": "itm_dragonscale_mail", "name": "Dragonscale Mail", "kind": "armor",
     "price": 350, "min_level": 5, "defense": 7},
    {"item_id": "itm_ember_plate", "name": "Ember Plate", "kind": "armor",
     "price": 500, "min_level": 5, "defense": 9},
    {"item_id": "itm_elixir", "name": "Elixir", "kind": "potion",
     "price": 90, "min_level": 5, "heal": 45},
]

# What the merchant pays for monster trophies, scaled by source-monster
# strength (weakest drop cheapest). Only these drop IDs are sellable —
# gear and potions are never bought back (blocks buy->sell gold loops).
# Prices sit below quest gold rewards so quests stay the best income.
MERCHANT_BUYBACK = {
    "itm_rat_pelt": 4,       # Giant Rat (8 HP)
    "itm_wolf_pelt": 8,      # Forest Wolf (14 HP)
    "itm_bandit_dagger": 15,  # Road Bandit (16 HP)
    "itm_wraith_essence": 20,  # Marsh Wraith (22 HP)
    "itm_troll_hide": 30,    # Cave Troll (30 HP)
    "itm_drake_scale": 60,   # Ember Drake (45 HP)
}


def merchant_npc():
    """The single trading NPC dict, or None."""
    return next((n for n in NPCS if n["npc_id"] == MERCHANT_ID), None)


def shop_for(npc_id):
    """Buyable stock for an NPC: full tiered catalog for the merchant, [] otherwise."""
    if npc_id == MERCHANT_ID:
        return [dict(s) for s in ARMORER_STOCK]
    return []


def buys_for(npc_id):
    """Buyback offers for an NPC: trophy prices for the merchant, [] otherwise."""
    if npc_id != MERCHANT_ID:
        return []
    names = {v["item_id"]: v["name"] for spec in MONSTER_DROPS.values()
             for v in [spec]}
    return [{"item_id": iid, "name": names.get(iid, iid), "price": price}
            for iid, price in MERCHANT_BUYBACK.items()]


def stock_spec(item_id):
    """Catalog spec for a buyable item_id, or None."""
    return next((s for s in ARMORER_STOCK if s["item_id"] == item_id), None)

STARTER_INVENTORY = [
    {"item_id": "itm_rusty_sword", "name": "Rusty Sword", "qty": 1, "equipped": True, "bonus": 1},
    {"item_id": "itm_healing_potion", "name": "Healing Potion", "qty": 1, "equipped": False, "heal": 12},
]

MONSTER_SPAWNS = [
    {"id": "mon_rat_1", "name": "Giant Rat", "location": "oakhollow_forest", "hp": 8, "xp_reward": 20, "gold_reward": 6},
    {"id": "mon_rat_2", "name": "Giant Rat", "location": "oakhollow_forest", "hp": 8, "xp_reward": 20, "gold_reward": 6},
    {"id": "mon_rat_3", "name": "Giant Rat", "location": "oakhollow_forest", "hp": 8, "xp_reward": 20, "gold_reward": 6},
    {"id": "mon_wolf_1", "name": "Forest Wolf", "location": "oakhollow_forest", "hp": 14, "xp_reward": 35, "gold_reward": 10},
    {"id": "mon_wolf_2", "name": "Forest Wolf", "location": "oakhollow_forest", "hp": 14, "xp_reward": 35, "gold_reward": 10},
    {"id": "mon_wolf_3", "name": "Forest Wolf", "location": "oakhollow_forest", "hp": 14, "xp_reward": 35, "gold_reward": 10},
    {"id": "mon_troll_1", "name": "Cave Troll", "location": "deep_cave", "hp": 30, "xp_reward": 80, "gold_reward": 40},
    {"id": "mon_troll_2", "name": "Cave Troll", "location": "deep_cave", "hp": 30, "xp_reward": 80, "gold_reward": 40},
    {"id": "mon_troll_3", "name": "Cave Troll", "location": "deep_cave", "hp": 30, "xp_reward": 80, "gold_reward": 40},
    {"id": "mon_troll_4", "name": "Cave Troll", "location": "deep_cave", "hp": 30, "xp_reward": 80, "gold_reward": 40},
    {"id": "mon_wraith_1", "name": "Marsh Wraith", "location": "sunken_marsh", "hp": 22, "xp_reward": 60, "gold_reward": 25},
    {"id": "mon_wraith_2", "name": "Marsh Wraith", "location": "sunken_marsh", "hp": 22, "xp_reward": 60, "gold_reward": 25},
    {"id": "mon_wraith_3", "name": "Marsh Wraith", "location": "sunken_marsh", "hp": 22, "xp_reward": 60, "gold_reward": 25},
    {"id": "mon_drake_1", "name": "Ember Drake", "location": "ember_ridge", "hp": 45, "xp_reward": 140, "gold_reward": 90},
    {"id": "mon_drake_2", "name": "Ember Drake", "location": "ember_ridge", "hp": 45, "xp_reward": 140, "gold_reward": 90},
    {"id": "mon_bandit_1", "name": "Road Bandit", "location": "capital_city", "hp": 16, "xp_reward": 40, "gold_reward": 20},
    {"id": "mon_bandit_2", "name": "Road Bandit", "location": "capital_city", "hp": 16, "xp_reward": 40, "gold_reward": 20},
]

# Hard cap: no location ever holds more than this many monster rows.
MAX_MONSTERS_PER_LOCATION = 10


MONSTER_DROPS = {
    # monster name -> guaranteed/chance item drop shown on kill
    "Giant Rat": {"item_id": "itm_rat_pelt", "name": "Rat Pelt", "chance": 1.0},
    "Forest Wolf": {"item_id": "itm_wolf_pelt", "name": "Wolf Pelt", "chance": 0.6},
    "Cave Troll": {"item_id": "itm_troll_hide", "name": "Troll Hide", "chance": 0.8},
    "Marsh Wraith": {"item_id": "itm_wraith_essence", "name": "Wraith Essence", "chance": 0.7},
    "Ember Drake": {"item_id": "itm_drake_scale", "name": "Drake Scale", "chance": 0.6},
    "Road Bandit": {"item_id": "itm_bandit_dagger", "name": "Bandit Dagger", "chance": 0.5, "bonus": 2},
}


def roll_drop(monster_name):
    """Return the drop dict or None. Uses module random (seed it in tests)."""
    import random
    spec = MONSTER_DROPS.get(monster_name)
    if not spec:
        return None
    if random.random() < spec.get("chance", 0):
        return {"item_id": spec["item_id"], "name": spec["name"],
                "qty": 1, "equipped": False, **({"bonus": spec["bonus"]} if "bonus" in spec else {})}
    return None


def seed_monsters(db):
    # Backfill-safe: inserts any spawn ids missing from this DB (so live
    # worlds gain new monsters on reboot) while respecting the per-location cap.
    existing = {m.id for m in db.query(Monster.id).all()}
    per_loc = {}
    for m in db.query(Monster.location).all():
        per_loc[m.location] = per_loc.get(m.location, 0) + 1
    for m in MONSTER_SPAWNS:
        if m["id"] in existing:
            continue
        per_loc[m["location"]] = per_loc.get(m["location"], 0) + 1
        if per_loc[m["location"]] > MAX_MONSTERS_PER_LOCATION:
            per_loc[m["location"]] -= 1
            continue  # respect the per-location cap
        db.add(Monster(id=m["id"], name=m["name"], location=m["location"],
                       hp=m["hp"], max_hp=m["hp"],
                       xp_reward=m["xp_reward"], gold_reward=m["gold_reward"], alive=True))
    db.commit()


GROUND_LOOT = [
    {"item_id": "itm_healing_potion", "name": "Healing Potion", "location": "riverside_village", "qty": 1, "heal": 12},
    {"item_id": "itm_wolf_pelt", "name": "Wolf Pelt", "location": "oakhollow_forest", "qty": 1},
    {"item_id": "itm_healing_potion", "name": "Healing Potion", "location": "oakhollow_forest", "qty": 1, "heal": 12},
    {"item_id": "itm_iron_sword", "name": "Iron Sword", "location": "deep_cave", "qty": 1, "bonus": 3},
    {"item_id": "itm_wraith_essence", "name": "Wraith Essence", "location": "sunken_marsh", "qty": 1},
    {"item_id": "itm_healing_potion", "name": "Healing Potion", "location": "capital_city", "qty": 1, "heal": 12},
]


def seed_ground(db):
    from .models import GroundItem
    if db.query(GroundItem).count() > 0:
        return
    for g in GROUND_LOOT:
        db.add(GroundItem(item_id=g["item_id"], name=g["name"],
                          location=g["location"], qty=g["qty"]))
    db.commit()


def ground_item_props(item_id):
    """Full item props (heal/bonus/defense) for a ground item_id, so pick_up keeps them."""
    for g in GROUND_LOOT:
        if g["item_id"] == item_id:
            return {k: v for k, v in g.items() if k not in ("location",)}
    for s in ARMORER_STOCK:
        if s["item_id"] == item_id:
            props = {"item_id": s["item_id"], "name": s["name"], "qty": 1}
            for k in ("bonus", "defense", "heal"):
                if k in s:
                    props[k] = s[k]
            return props
    for spec in MONSTER_DROPS.values():
        if spec["item_id"] == item_id:
            return {"item_id": spec["item_id"], "name": spec["name"], "qty": 1,
                    **({"bonus": spec["bonus"]} if "bonus" in spec else {})}
    return None


def exits_from(loc_id):
    out = []
    for e in EDGES:
        if e["from"] == loc_id:
            out.append({"to": e["to"], "direction": e["direction"]})
        elif e["to"] == loc_id:
            out.append({"to": e["from"], "direction": "back"})
    return out


def loc_by_id(loc_id):
    return next((l for l in LOCATIONS if l["id"] == loc_id), None)


def monster_haunts(monster_name):
    """Location names where a monster type spawns, e.g. ['Oakhollow Forest']."""
    seen, out = set(), []
    for m in MONSTER_SPAWNS:
        if m["name"] == monster_name and m["location"] not in seen:
            seen.add(m["location"])
            loc = loc_by_id(m["location"])
            out.append(loc["name"] if loc else m["location"])
    return out


def danger_of(location_id):
    """Static danger rating from the strongest thing that spawns there."""
    strongest = max((m["hp"] for m in MONSTER_SPAWNS if m["location"] == location_id), default=0)
    if strongest >= 30:
        return "deadly"
    if strongest >= 15:
        return "dangerous"
    if strongest > 0:
        return "mild"
    return "safe"


def monster_for_item(item_id):
    """Source monster name whose drop table yields item_id, e.g. 'Forest Wolf'."""
    for monster_name, spec in MONSTER_DROPS.items():
        if spec.get("item_id") == item_id:
            return monster_name
    return None


def quests_at(location_id):
    """Quest offers available from NPCs at this location, with full terms."""
    out = []
    for qid, q in QUESTS.items():
        giver = next((n for n in NPCS if n["npc_id"] == q["giver"] and n["location"] == location_id), None)
        if giver:
            out.append({"quest_id": qid, "title": q["title"], "kind": q.get("kind", "collect"),
                        "item_id": q["item_id"], "item_name": q["item_name"],
                        "count": q["count"], "xp": q["xp"], "gold": q["gold"],
                        "min_level": q.get("min_level", 1),
                        "giver": giver["name"], "brief": quest_brief(qid)})
    return out


def quest_brief(quest_id):
    """One-line explicit briefing: requirement, item, source, where, reward."""
    spec = QUESTS.get(quest_id)
    if not spec:
        return ""
    source = monster_for_item(spec["item_id"])
    where = ", ".join(monster_haunts(source)) if source else ""
    where = where or "the wilds"
    chance = MONSTER_DROPS.get(source, {}).get("chance") if source else None
    odds = f", {int(chance * 100)}% drop" if chance is not None else ""
    req = f"Requires level {spec.get('min_level', 1)}. "
    return (f"{req}Bring {spec['count']}x {spec['item_name']} "
            f"(dropped by {source} in {where}{odds}); reward: +{spec['xp']} XP, +{spec['gold']} gold. "
            f"Turn-in consumes the items.")
