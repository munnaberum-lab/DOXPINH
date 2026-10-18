"""⚡ Dotxbrain Uptime Pro — database layer.

PRIVACY: every user-facing query is filtered by `owner`, so one user can never read,
change or delete another user's monitors — even if an id is guessed.
`uid` is coerced with int() and ids with str(), which also blocks NoSQL operator injection
(e.g. {"$ne": None}). Only `due()` is cross-user, and it is used by the background worker only.
"""
import copy, logging, time

import info as cfg

log = logging.getLogger("dotxbrain.db")
ALLOWED_FIELDS = {"paused", "interval", "next_check", "name", "muted"}
USER_FIELDS = {"banned", "notify", "limit", "name"}


def _check_fields(fields, allowed=ALLOWED_FIELDS):
    bad = set(fields) - allowed
    if bad: raise ValueError(f"fields not allowed: {sorted(bad)}")


class MemoryDB:
    """Temporary storage (lost on restart). Used when MONGO_URI is empty."""
    name = "memory"

    def __init__(self): self.mon, self.users, self.settings = {}, {}, {}

    async def init(self):
        log.warning("MONGO_URI is empty → using TEMPORARY in-memory database (data lost on restart)")

    async def upsert_user(self, uid, name):
        u = self.users.setdefault(int(uid), {"joined": int(time.time())})
        u.update(name=str(name)[:64], seen=int(time.time()))

    async def get_user(self, uid):
        u = self.users.get(int(uid)); return {**copy.deepcopy(u), "_id": int(uid)} if u else None

    async def list_users(self): return [{**copy.deepcopy(u), "_id": k} for k, u in self.users.items()]

    async def set_user(self, uid, fields):
        _check_fields(fields, USER_FIELDS)
        self.users.setdefault(int(uid), {"joined": int(time.time())}).update(fields)

    async def all_monitors(self): return [copy.deepcopy(x) for x in self.mon.values()]

    async def delete_user_monitors(self, uid):
        ids = [k for k, x in self.mon.items() if x["owner"] == int(uid)]
        for k in ids: del self.mon[k]
        return len(ids)

    async def load_settings(self): return dict(self.settings)
    async def save_setting(self, k, v): self.settings[str(k)] = v

    async def insert(self, m):
        if m["_id"] in self.mon or any(x["owner"] == m["owner"] and x["url"] == m["url"] for x in self.mon.values()):
            return False
        self.mon[m["_id"]] = copy.deepcopy(m); return True

    async def get(self, uid, mid):
        uid, mid = int(uid), str(mid)
        x = self.mon.get(mid)
        return copy.deepcopy(x) if x and x["owner"] == uid else None

    async def list(self, uid):
        uid = int(uid)
        return sorted((copy.deepcopy(x) for x in self.mon.values() if x["owner"] == uid), key=lambda x: x["created"])

    async def count(self, uid): return len(await self.list(uid))
    async def exists(self, uid, url): return any(x["url"] == url for x in await self.list(uid))

    async def set_fields(self, uid, mid, fields):
        _check_fields(fields)
        x = self.mon.get(str(mid))
        if not x or x["owner"] != int(uid): return False
        x.update(fields); return True

    async def apply(self, uid, mid, d):
        x = self.mon.get(str(mid))
        if not x or x["owner"] != int(uid): return False
        x.update(d["set"])
        for k, v in d["inc"].items(): x[k] = x.get(k, 0) + v
        x["logs"] = (x.get("logs", []) + [d["log"]])[-cfg.LOG_KEEP:]
        return True

    async def delete(self, uid, mid):
        x = self.mon.get(str(mid))
        if not x or x["owner"] != int(uid): return False
        del self.mon[x["_id"]]; return True

    async def due(self, now):
        return [copy.deepcopy(x) for x in self.mon.values() if not x["paused"] and x["next_check"] <= now]


class MongoDB:
    """MongoDB (Atlas or self-hosted) via motor."""
    name = "mongodb"

    def __init__(self, uri, dbname):
        from motor.motor_asyncio import AsyncIOMotorClient
        self.client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=8000, appname="DotxbrainUptimePro")
        db = self.client[dbname]
        self.mon, self.users, self.cfg = db["monitors"], db["users"], db["settings"]

    async def init(self):
        await self.client.admin.command("ping")                     # fail fast on bad URI / network
        await self.mon.create_index([("owner", 1), ("url", 1)], unique=True)
        await self.mon.create_index([("paused", 1), ("next_check", 1)])
        log.info("MongoDB connected ✓")

    async def upsert_user(self, uid, name):
        await self.users.update_one({"_id": int(uid)},
                                    {"$set": {"name": str(name)[:64], "seen": int(time.time())},
                                     "$setOnInsert": {"joined": int(time.time())}}, upsert=True)

    async def get_user(self, uid): return await self.users.find_one({"_id": int(uid)})
    async def list_users(self): return await self.users.find({}).to_list(length=20000)

    async def set_user(self, uid, fields):
        _check_fields(fields, USER_FIELDS)
        await self.users.update_one({"_id": int(uid)}, {"$set": fields, "$setOnInsert": {"joined": int(time.time())}}, upsert=True)

    async def all_monitors(self): return await self.mon.find({}).to_list(length=20000)

    async def delete_user_monitors(self, uid):
        r = await self.mon.delete_many({"owner": int(uid)}); return r.deleted_count

    async def load_settings(self):
        d = await self.cfg.find_one({"_id": "global"}) or {}
        d.pop("_id", None); return d

    async def save_setting(self, k, v):
        await self.cfg.update_one({"_id": "global"}, {"$set": {str(k): v}}, upsert=True)

    async def insert(self, m):
        from pymongo.errors import DuplicateKeyError
        try:
            await self.mon.insert_one(dict(m)); return True
        except DuplicateKeyError:
            return False

    async def get(self, uid, mid):
        return await self.mon.find_one({"_id": str(mid), "owner": int(uid)})

    async def list(self, uid):
        docs = await self.mon.find({"owner": int(uid)}).to_list(length=500)
        return sorted(docs, key=lambda x: x["created"])

    async def count(self, uid): return await self.mon.count_documents({"owner": int(uid)})
    async def exists(self, uid, url): return await self.mon.count_documents({"owner": int(uid), "url": url}) > 0

    async def set_fields(self, uid, mid, fields):
        _check_fields(fields)
        r = await self.mon.update_one({"_id": str(mid), "owner": int(uid)}, {"$set": fields})
        return r.matched_count > 0

    async def apply(self, uid, mid, d):
        r = await self.mon.update_one({"_id": str(mid), "owner": int(uid)},
                                      {"$set": d["set"], "$inc": d["inc"],
                                       "$push": {"logs": {"$each": [d["log"]], "$slice": -cfg.LOG_KEEP}}})
        return r.matched_count > 0

    async def delete(self, uid, mid):
        r = await self.mon.delete_one({"_id": str(mid), "owner": int(uid)})
        return r.deleted_count > 0

    async def due(self, now):
        return await self.mon.find({"paused": False, "next_check": {"$lte": int(now)}}).to_list(length=1000)


async def create_db():
    db = MongoDB(cfg.MONGO_URI, cfg.MONGO_DB) if cfg.MONGO_URI else MemoryDB()
    await db.init()
    return db
