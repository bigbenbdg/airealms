"""SQLAlchemy models. JSON columns keep SQLite simple; same shape maps to Postgres JSONB."""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True)              # agt_xxxx
    api_key = Column(String, unique=True, index=True)  # sk_live_... (hash in prod)
    name = Column(String(40))
    bio = Column(String(200), default="")
    owner_contact = Column(String(120), default="")
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    hp = Column(Integer, default=25)
    max_hp = Column(Integer, default=25)
    stats = Column(Text, default='{"str": 3, "dex": 3, "int": 2, "luck": 2}')  # JSON
    gold = Column(Integer, default=20)
    location = Column(String, default="riverside_village")
    inventory = Column(Text, default="[]")   # JSON list [{item_id,name,qty,equipped}]
    quests = Column(Text, default="[]")      # JSON list [{quest_id,title,progress,done}]
    kills = Column(Integer, default=0)
    quests_completed = Column(Integer, default=0)
    alive = Column(Boolean, default=True)
    cooldown_until = Column(DateTime, default=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    registered_at = Column(DateTime, default=utcnow)


class Monster(Base):
    __tablename__ = "monsters"
    id = Column(String, primary_key=True)  # mon_xxxx
    name = Column(String, primary_key=False)
    location = Column(String, index=True)
    hp = Column(Integer)
    max_hp = Column(Integer)
    xp_reward = Column(Integer, default=20)
    gold_reward = Column(Integer, default=5)
    alive = Column(Boolean, default=True)
    died_at = Column(DateTime, nullable=True)  # set on death; drives respawn


class GroundItem(Base):
    """Loot lying on the ground. Visible to spectators, pickable via pick_up."""
    __tablename__ = "ground_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String, index=True)   # e.g. itm_healing_potion
    name = Column(String)
    location = Column(String, index=True)
    qty = Column(Integer, default=1)


class WorldEvent(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, index=True)  # level_up|death|quest|loot|combat|chat|register
    agent = Column(String, default="")
    agent_id = Column(String, default="")
    detail = Column(String, default="")
    at = Column(DateTime, default=utcnow)
