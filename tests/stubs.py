"""Tiny stand-ins for aiohttp / aiogram / motor / pymongo so the whole project can be tested
offline. They mimic the behaviours that matter (Telegram button rules, Mongo operators, unique
indexes, NoSQL operator matching) so real bugs show up here too."""
import asyncio, copy, sys, types
from types import SimpleNamespace


def _mod(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m


# ───────────────────────── aiohttp ─────────────────────────
class ClientError(Exception): pass
class ClientTimeout:
    def __init__(self, total=None): self.total = total
class ClientSession:
    def __init__(self, *a, **k): self.closed = False
    async def close(self): self.closed = True

class HTTPException(Exception): status = 500
class HTTPUnauthorized(HTTPException):
    status = 401
    def __init__(self, text=""): super().__init__(text); self.text = text

class Application(dict):
    def __init__(self, middlewares=(), client_max_size=0):
        super().__init__(); self.middlewares = list(middlewares); self.routes = []
    def add_routes(self, r): self.routes += r

class _Runner:
    def __init__(self, app): self.app = app; self.cleaned = False
    async def setup(self): pass
    async def cleanup(self): self.cleaned = True
class _Site:
    def __init__(self, runner, host, port): self.port = port
    async def start(self): pass


# ───────────────────────── aiogram ─────────────────────────
class MF:
    """Mini MagicFilter: supports F.data == x, F.data.startswith(x), F.text & ~F.text.startswith(x)."""
    def __init__(self, fn=lambda o: o): self.fn = fn
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return MF(lambda o, f=self.fn: getattr(f(o), n, None))
    def __call__(self, *a): return MF(lambda o, f=self.fn: f(o)(*a) if callable(f(o)) else False)
    def __eq__(self, v): return MF(lambda o, f=self.fn: f(o) == v)
    def __and__(self, other): return MF(lambda o, f=self.fn: bool(f(o)) and bool(other.fn(o)))
    def __or__(self, other): return MF(lambda o, f=self.fn: bool(f(o)) or bool(other.fn(o)))
    def __invert__(self): return MF(lambda o, f=self.fn: not f(o))
    __hash__ = object.__hash__
    def resolve(self, o): return self.fn(o)

class Command:
    def __init__(self, name): self.name = name
    def match(self, msg):
        t = getattr(msg, "text", None) or ""
        return t == f"/{self.name}" or t.startswith(f"/{self.name} ")
class CommandStart(Command):
    def __init__(self): super().__init__("start")

class _Observer:
    def __init__(self, router, kind): self.router, self.kind = router, kind
    def __call__(self, *filters):
        def deco(fn): self.router.handlers.append((self.kind, filters, fn)); return fn
        return deco
    def middleware(self, mw): self.router.middlewares[self.kind].append(mw)

class Router:
    def __init__(self):
        self.handlers = []; self.middlewares = {"message": [], "callback_query": []}
        self.message = _Observer(self, "message"); self.callback_query = _Observer(self, "callback_query")

class BaseMiddleware: pass
class TelegramBadRequest(Exception): pass

class InlineKeyboardButton:
    def __init__(self, text, callback_data=None, url=None, web_app=None):
        actions = [x for x in (callback_data, url, web_app) if x is not None]
        if len(actions) != 1: raise ValueError("button needs exactly one action")     # Telegram rule
        if callback_data is not None and len(callback_data.encode()) > 64: raise ValueError("callback_data > 64 bytes")
        if not text: raise ValueError("empty button text")
        self.text, self.callback_data, self.url, self.web_app = text, callback_data, url, web_app
class InlineKeyboardMarkup:
    def __init__(self, inline_keyboard): self.inline_keyboard = inline_keyboard
class WebAppInfo:
    def __init__(self, url):
        if not url.startswith("https://"): raise ValueError("WebApp url must be https")
        self.url = url
class MenuButtonWebApp:
    def __init__(self, text, web_app): self.text, self.web_app = text, web_app
class BotCommand:
    def __init__(self, command, description): self.command, self.description = command, description
class Message: pass
class CallbackQuery: pass

class Bot:
    instances = []
    def __init__(self, token, default=None):
        self.token, self.default, self.calls = token, default, []
        self.session = SimpleNamespace(close=self._close); self.closed = False
        Bot.instances.append(self)
    async def _close(self): self.closed = True
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        async def call(*a, **k): self.calls.append((name, a, k)); return True
        return call
class Dispatcher:
    def __init__(self): self.routers = []; self.polled = False
    def include_router(self, r): self.routers.append(r)
    async def start_polling(self, bot): self.polled = True


# ───────────────────────── pymongo / motor (fake MongoDB) ─────────────────────────
class DuplicateKeyError(Exception): pass

def _match(doc, q):
    for k, v in q.items():
        dv = doc.get(k)
        if isinstance(v, dict):                       # operators behave like real MongoDB
            for op, x in v.items():
                if op == "$lte":
                    if dv is None or not dv <= x: return False
                elif op == "$ne":
                    if dv == x: return False
                else: raise NotImplementedError(op)
        elif dv != v: return False
    return True

class _Cursor:
    def __init__(self, docs): self.docs = docs
    async def to_list(self, length=None):
        return copy.deepcopy(self.docs if length is None else self.docs[:length])

class Collection:
    def __init__(self): self.docs, self.unique = [], []
    async def create_index(self, keys, unique=False, **kw):
        if unique: self.unique.append([keys] if isinstance(keys, str) else [k for k, _ in keys])
        return "ix"
    async def insert_one(self, doc):
        await asyncio.sleep(0)
        if any(d["_id"] == doc["_id"] for d in self.docs): raise DuplicateKeyError("_id")
        for ks in self.unique:
            if any(all(d.get(k) == doc.get(k) for k in ks) for d in self.docs): raise DuplicateKeyError(str(ks))
        self.docs.append(copy.deepcopy(doc)); return SimpleNamespace(inserted_id=doc["_id"])
    async def find_one(self, q):
        await asyncio.sleep(0)
        return next((copy.deepcopy(d) for d in self.docs if _match(d, q)), None)
    def find(self, q): return _Cursor([d for d in self.docs if _match(d, q)])
    async def count_documents(self, q):
        await asyncio.sleep(0); return sum(1 for d in self.docs if _match(d, q))
    async def delete_one(self, q):
        await asyncio.sleep(0)
        for d in self.docs:
            if _match(d, q): self.docs.remove(d); return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)
    async def delete_many(self, q):
        await asyncio.sleep(0); keep = [d for d in self.docs if not _match(d, q)]
        n = len(self.docs) - len(keep); self.docs[:] = keep; return SimpleNamespace(deleted_count=n)
    async def update_one(self, q, u, upsert=False):
        await asyncio.sleep(0)
        bad = set(u) - {"$set", "$inc", "$push", "$setOnInsert"}
        if bad: raise NotImplementedError(bad)
        if any(v == {} for v in u.values()): raise ValueError("empty update operator")   # old MongoDB rule
        d = next((d for d in self.docs if _match(d, q)), None)
        if d is None:
            if not upsert: return SimpleNamespace(matched_count=0)
            d = {k: v for k, v in q.items() if not isinstance(v, dict)}; d.update(u.get("$setOnInsert", {}))
            self.docs.append(d)
        d.update(u.get("$set", {}))
        for k, v in u.get("$inc", {}).items(): d[k] = d.get(k, 0) + v
        for k, v in u.get("$push", {}).items():
            lst = d.setdefault(k, []); lst.extend(v["$each"]); sl = v.get("$slice")
            if sl is not None: d[k] = lst[sl:] if sl < 0 else lst[:sl]
        return SimpleNamespace(matched_count=1)

class _FakeDB(dict):
    def __missing__(self, k): self[k] = Collection(); return self[k]

class AsyncIOMotorClient:
    def __init__(self, uri, **kw): self.uri, self.kw, self.dbs = uri, kw, {}
    def __getitem__(self, name): return self.dbs.setdefault(name, _FakeDB())
    @property
    def admin(self):
        uri = self.uri
        async def command(c):
            if "bad" in uri: raise ConnectionError("ServerSelectionTimeoutError: no servers found")
            return {"ok": 1}
        return SimpleNamespace(command=command)


def install():
    _mod("aiohttp", ClientError=ClientError, ClientTimeout=ClientTimeout, ClientSession=ClientSession)
    web = _mod("aiohttp.web", HTTPException=HTTPException, HTTPUnauthorized=HTTPUnauthorized,
               Application=Application, AppRunner=_Runner, TCPSite=_Site, middleware=lambda f: f,
               json_response=lambda data, status=200, **k: SimpleNamespace(status=status, data=data),
               Response=lambda text="", status=200: SimpleNamespace(status=status, text=text),
               FileResponse=lambda path, headers=None: SimpleNamespace(status=200, path=str(path), headers=headers),
               get=lambda p, h: ("GET", p, h), post=lambda p, h: ("POST", p, h))
    sys.modules["aiohttp"].web = web
    _mod("aiogram", Bot=Bot, Dispatcher=Dispatcher, F=MF(), Router=Router, BaseMiddleware=BaseMiddleware)
    _mod("aiogram.client"); _mod("aiogram.client.default", DefaultBotProperties=lambda **k: SimpleNamespace(**k))
    _mod("aiogram.enums", ParseMode=SimpleNamespace(HTML="HTML"))
    _mod("aiogram.exceptions", TelegramBadRequest=TelegramBadRequest)
    _mod("aiogram.filters", Command=Command, CommandStart=CommandStart)
    _mod("aiogram.types", InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
         WebAppInfo=WebAppInfo, MenuButtonWebApp=MenuButtonWebApp, BotCommand=BotCommand,
         Message=Message, CallbackQuery=CallbackQuery)
    _mod("motor"); _mod("motor.motor_asyncio", AsyncIOMotorClient=AsyncIOMotorClient)
    _mod("pymongo"); _mod("pymongo.errors", DuplicateKeyError=DuplicateKeyError)
