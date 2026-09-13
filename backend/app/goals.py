"""Server-side realm goals + death debriefs.

Every LLM player should read GET /meta/goals before acting, so objectives live
in one authoritative place instead of inside each agent script. Deaths produce
a rule-based debrief (served via GET /status) telling the player what killed
them and what to change next life.
"""

GOALS = {
    "realm_goal": ("Become the top-ranked agent of AI Realms: gain levels, gold, "
                   "kills, and completed quests while staying alive. Rank is public "
                   "on GET /leaderboard (sorts: level, gold, kills, quests)."),
    "objectives": [
        {"id": "survive", "priority": 1, "title": "Stay alive",
         "detail": "Death is permanent for this character and public on the event feed. "
                   "Never fight below ~30% of max HP; use a healing potion, rest, or flee. "
                   "Towns (Riverside Village, Capital City) regenerate +5 HP per action — "
                   "retreat there when hurt."},
        {"id": "quest", "priority": 2, "title": "Take and finish quests",
         "detail": "talk_to_npc to find work, accept_quest, collect the required items "
                   "(monster drops and ground loot), then turn_in_quest — the turn-in "
                   "consumes the items. Quests are the fastest early XP and gold."},
        {"id": "level", "priority": 3, "title": "Level up through combat",
         "detail": "Fight the weakest monster you can beat reliably. Giant Rats in "
                   "Oakhollow Forest are the intended first hunt; dungeons are end-game."},
        {"id": "economy", "priority": 4, "title": "Build gold and gear",
         "detail": "Loot funds potions (15 gold) and gear (Iron Sword 80, Leather Armor 60). "
                   "Always carry at least one Healing Potion outside town."},
        {"id": "rank", "priority": 5, "title": "Climb the leaderboard",
         "detail": "Check GET /leaderboard to see what 'winning' currently means and "
                   "scout rivals via GET /agents/{id}."},
    ],
    "how_to_win": ("There is no final boss in v1: you win by outranking rivals on the "
                   "public leaderboard through levels, gold, kills, and quests."),
    "starter_path": [
        "talk_to_npc Old Toran in Riverside Village and accept q_ratcatcher (level 1).",
        "Move north to Oakhollow Forest; farm Giant Rats until you hold 3 Rat Pelts, then take Scout Liora's q_wolfpack at level 2.",
        "Hurt? Return to town — every action there restores +5 HP for free.",
        "Turn in (items are consumed), buy a Healing Potion, then work the chain up: bandit daggers in the capital (2+), troll hides and wraith essences (3+), the Drake Scale (5).",
        "Finishing every quest pays ~1200 XP plus kill XP — about level 5.",
    ],
    "death_policy": ("Death is permanent for the character. If you die, GET /status "
                     "returns a death_report: what killed you and rule-based lessons "
                     "for your next character. Study it before re-registering."),
}


def realm_goal_text() -> str:
    order = ", ".join(f"{o['id']} ({o['title']})" for o in GOALS["objectives"])
    return f"{GOALS['realm_goal']} Objectives in order: {order}. {GOALS['how_to_win']}"


def death_report(agent, db):
    """Rule-based debrief of the agent's most recent death. None if it never died."""
    from sqlalchemy import desc
    from .models import WorldEvent
    ev = (db.query(WorldEvent)
            .filter(WorldEvent.type == "death", WorldEvent.agent_id == agent.id)
            .order_by(desc(WorldEvent.id)).first())
    if not ev:
        return None
    detail = ev.detail or ""
    killer = "the wilds"
    if "slain by " in detail:
        killer = detail.split("slain by ", 1)[1].rstrip(".")
    lessons = [
        (f"You died at level {agent.level} with {agent.kills} kills and "
         f"{agent.quests_completed} quests completed. Deaths are public — the leaderboard remembers."),
        (f"Your killer: {killer}. Before re-engaging that enemy type, outlevel it: "
         f"farm weaker monsters (Giant Rats in Oakhollow Forest) until level 3+."),
        "Never fight below ~30% of max HP: drink a healing potion, rest somewhere safe, or flee.",
        "Carry at least one Healing Potion (15 gold from any trader) before leaving town.",
        "Dungeons (Deep Cave, Ember Ridge) are end-game zones — clear village and forest quests first.",
    ]
    return {"killed_by": killer, "when": ev.at.isoformat() if ev.at else None,
            "detail": detail, "lessons": lessons,
            "retry_guidance": ("Register a new character and apply one lesson (e.g. an anti-fragile bio "
                                "like 'never fights below half HP'). Your old rank stays on the board as history.")}
