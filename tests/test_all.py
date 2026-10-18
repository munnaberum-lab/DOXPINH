"""Offline test-suite for Dotxbrain Uptime Pro.   Run:  python3 tests/test_all.py"""
import asyncio, functools, hashlib, hmac, json, logging, os, py_compile, sys, time, unittest, urllib.parse
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
import stubs; stubs.install()
if not os.getenv("DEBUG"): logging.disable(logging.CRITICAL)

import info as cfg
import core, db as dbm, bot as botmod, admin_bot, admin as adminmod, templates, api, worker, main as mainmod

BRAND = core.BRAND_SC
WRONG = core.sc("something went wrong")
PATCH = dict(GH_TOKEN="", GH_REPO="", GH_BRANCH="main", MAX_MONITORS_PER_USER=3, SLOW_MS=8000, WAKE_TIMEOUT=0.15, AUTO_WAKE=True, BOT_TOKEN="123:ABC",
             BASE_URL="https://dx.onrender.com", BRAND_LINK="", QUICK_COOLDOWN=10, LOG_KEEP=50, MONGO_URI="")
BACKENDS = [("memory", lambda: dbm.MemoryDB()), ("mongo", lambda: dbm.MongoDB("mongodb://fake", "t"))]
HOSTS = {}
BAD = object()


# ───────────────────────── fakes ─────────────────────────
class _Resp:
    def __init__(s, status=200, body=b"ok"):
        s.status, s.headers = status, {"server": "test", "content-length": str(len(body))}
        async def read(n): return body
        s.content = SimpleNamespace(read=read)

class _Ctx:
    def __init__(s, item): s.item = item
    async def __aenter__(s):
        it = s.item
        if isinstance(it, BaseException) or (isinstance(it, type) and issubclass(it, BaseException)): raise it
        return _Resp(it) if isinstance(it, int) else _Resp(*it)
    async def __aexit__(s, *a): return False

class FakeSession:
    def __init__(s): s.script, s.calls, s.posts, s.post_status = {}, [], [], 204
    def post(s, url, **kw):
        s.posts.append((url, kw)); return _Ctx(s.post_status)
    def get(s, url, **kw):
        s.calls.append((url, kw)); q = s.script.get(url)
        return _Ctx((q.pop(0) if len(q) > 1 else q[0]) if q else 200)

async def resolver(host): return HOSTS.get(host, ["93.184.216.34"])

def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f: return f.read()

def make_init(uid, token="123:ABC", age=0, user=None):
    d = {"auth_date": str(int(time.time()) - age), "query_id": "AAH", "user": json.dumps(user or {"id": uid, "first_name": "T"})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    d["hash"] = hmac.new(hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest(), chk.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(d)

class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved = {k: getattr(cfg, k) for k in PATCH}
        for k, v in PATCH.items(): setattr(cfg, k, v)
        self._gap, core.WAKE_GAP = core.WAKE_GAP, 0.01
        botmod.WAITING.clear(); botmod.PENDING.clear(); botmod.LAST_QUICK.clear(); admin_bot.BCAST.clear(); HOSTS.clear()
        self._admins, cfg.ADMIN_IDS = cfg.ADMIN_IDS, {99}
    def tearDown(self):
        for k, v in self._saved.items(): setattr(cfg, k, v)
        cfg.ADMIN_IDS = self._admins
        core.WAKE_GAP = self._gap
    async def env(self, factory=BACKENDS[0][1]):
        db = factory(); await db.init()
        sess = FakeSession(); svc = core.Service(db, sess); svc.resolve = resolver
        return db, sess, svc


# ───────────────────────── helpers / security ─────────────────────────
class TestHelpers(unittest.TestCase):
    def test_small_caps_and_brand(self):
        self.assertEqual(core.sc("Wake Up 24/7"), "ᴡᴀᴋᴇ ᴜᴘ 24/7")
        self.assertEqual(BRAND, "ᴅᴏᴛxʙʀᴀɪɴ")
        self.assertIn(BRAND, core.branded("hello")); self.assertEqual(core.branded("a " + BRAND), "a " + BRAND)

    def test_norm_url(self):
        ok = ["https://a.onrender.com", "a.onrender.com", "http://a.com:8080/x?y=1", "HTTPS://A.COM", "https://8.8.8.8"]
        bad = ["", "   ", None, 5, "localhost", "http://localhost:3000", "http://127.0.0.1", "10.0.0.5", "192.168.1.1",
               "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "ftp://x.com",
               "javascript:alert(1)", "file:///etc/passwd", "a b.com", "https://x", "http://x.local", "http://svc.internal",
               "https://a.com:99999", "a" * 3000 + ".com", "https://100.64.0.1"]
        for u in ok: self.assertIsNotNone(core.norm_url(u), u)
        for u in bad: self.assertIsNone(core.norm_url(u), u)

    def test_verify_init(self):
        self.assertEqual(core.verify_init(make_init(42), "123:ABC"), 42)
        self.assertIsNone(core.verify_init(make_init(42, token="999:ZZZ"), "123:ABC"))
        self.assertIsNone(core.verify_init(make_init(42, age=90000), "123:ABC"))
        t = make_init(42).replace("%2242%22", "%2243%22").replace('"id": 42', '"id": 43')
        self.assertIsNone(core.verify_init(t.replace("42", "43"), "123:ABC"))
        for junk in ["", "abc", "hash=", "hash=abc&user=%7B%7D", None, "a=b&hash=00"]:
            self.assertIsNone(core.verify_init(junk, "123:ABC"), junk)
        d = dict(urllib.parse.parse_qsl(make_init(42))); d.pop("user")           # valid hash impossible w/o user
        self.assertIsNone(core.verify_init(urllib.parse.urlencode(d), "123:ABC"))

    def test_files_branded_and_compile(self):
        for f in ("main", "core", "db", "bot", "api", "worker", "info", "admin", "admin_bot", "templates"):
            p = os.path.join(ROOT, f + ".py"); py_compile.compile(p, doraise=True)
            self.assertIn("Dotxbrain", read(f + ".py"), f)
        self.assertGreaterEqual(read("webapp/index.html").lower().count("dotxbrain"), 2)
        self.assertIn("dotxbrain", read("Dockerfile").lower()); self.assertIn("dotxbrain", read("README.md").lower())
        self.assertIn("motor", read("requirements.txt"))


# ───────────────────────── database (both backends) ─────────────────────────
class TestDB(Base):
    async def test_contract_and_privacy(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, _, _ = await self.env(fac)
                a = core.new_monitor(1, "https://a.com"); self.assertTrue(await db.insert(a))
                self.assertFalse(await db.insert(core.new_monitor(1, "https://a.com")))         # duplicate (owner,url)
                b = core.new_monitor(2, "https://a.com"); self.assertTrue(await db.insert(b))   # other owner OK
                self.assertEqual((await db.get(1, a["id"]))["url"], "https://a.com")
                self.assertIsNone(await db.get(2, a["id"]))                                      # privacy
                self.assertEqual([x["id"] for x in await db.list(1)], [a["id"]])
                self.assertEqual([x["id"] for x in await db.list(2)], [b["id"]])
                self.assertEqual(await db.count(1), 1); self.assertTrue(await db.exists(1, "https://a.com"))
                self.assertFalse(await db.exists(3, "https://a.com"))
                self.assertFalse(await db.set_fields(2, a["id"], {"paused": True}))
                self.assertFalse((await db.get(1, a["id"]))["paused"])
                self.assertTrue(await db.set_fields(1, a["id"], {"paused": True}))
                with self.assertRaises(ValueError): await db.set_fields(1, a["id"], {"owner": 99})
                with self.assertRaises(ValueError): await db.set_fields(1, a["id"], {"$set": 1})
                self.assertFalse(await db.delete(2, a["id"])); self.assertIsNotNone(await db.get(1, a["id"]))
                self.assertTrue(await db.delete(1, a["id"])); self.assertIsNone(await db.get(1, a["id"]))
                self.assertFalse(await db.delete(1, a["id"]))
                await db.upsert_user(1, "Ravi"); await db.upsert_user(1, "Ravi 2")

    async def test_apply_trims_logs(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, _, _ = await self.env(fac)
                m = core.new_monitor(1, "https://a.com"); await db.insert(m)
                r = dict(state="up", code=200, ms=5, note="ok")
                for _ in range(60): self.assertTrue(await db.apply(1, m["id"], core.apply_result(m, "ping", r)))
                s = await db.get(1, m["id"])
                self.assertEqual((s["total"], s["ok"], len(s["logs"])), (60, 60, 50))
                self.assertEqual(s["status"], "up"); self.assertEqual(len(m["logs"]), 50)
                self.assertFalse(await db.apply(2, m["id"], core.apply_result(m, "ping", r)))      # not the owner

    async def test_nosql_injection_blocked(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, _, _ = await self.env(fac)
                m = core.new_monitor(1, "https://a.com"); await db.insert(m)
                for owner in (1, 2):                                         # id operator → plain string, never matches
                    for evil in ({"$ne": None}, {"$ne": ""}, {"$gt": ""}):
                        self.assertIsNone(await db.get(owner, evil), (owner, evil))
                        self.assertFalse(await db.delete(owner, evil)); self.assertFalse(await db.set_fields(owner, evil, {"paused": True}))
                self.assertIsNotNone(await db.get(1, m["id"]))
                for bad_uid in ({"$ne": 0}, [1], None):
                    for fn in (db.list, db.count):
                        with self.assertRaises(TypeError): await fn(bad_uid)
                    with self.assertRaises(TypeError): await db.get(bad_uid, m["id"])

    async def test_due(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, _, _ = await self.env(fac)
                a, p, f = (core.new_monitor(1, f"https://{x}.com") for x in "apf")
                p["paused"] = True; f["next_check"] = int(time.time()) + 999
                for m in (a, p, f): await db.insert(m)
                self.assertEqual([m["id"] for m in await db.due(int(time.time()))], [a["id"]])


# ───────────────────────── service: probe / wake / add ─────────────────────────
class TestService(Base):
    async def test_probe_states(self):
        _, sess, svc = await self.env()
        cases = [(200, "up"), (404, "up"), (302, "up"), (204, "up"), (503, "sleeping"), (502, "sleeping"),
                 (504, "sleeping"), (500, "down"), ((200, b"<h1>Service Waking Up</h1>"), "sleeping"),
                 (asyncio.TimeoutError(), "sleeping"), (stubs.ClientError(), "down"), (ValueError("bad"), "down"),
                 (UnicodeError("idna"), "down")]
        for item, want in cases:
            sess.script["https://a.com"] = [item]
            self.assertEqual((await svc.probe("https://a.com"))["state"], want, item)

    async def test_probe_request_is_safe(self):
        _, sess, svc = await self.env(); await svc.probe("https://a.com")
        kw = sess.calls[0][1]
        self.assertFalse(kw["allow_redirects"]); self.assertIn("User-Agent", kw["headers"]); self.assertIn("text/html", kw["headers"]["Accept"])

    async def test_cold_start_detected(self):
        _, sess, svc = await self.env(); cfg.SLOW_MS = -1
        r = await svc.probe("https://a.com"); self.assertEqual(r["state"], "up"); self.assertTrue(r["cold"])

    async def test_ssrf_and_dns(self):
        _, sess, svc = await self.env()
        for ips in (["127.0.0.1"], ["10.0.0.9"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "192.168.0.1"], []):
            HOSTS["evil.com"] = ips; sess.calls.clear()
            r = await svc.probe("https://evil.com")
            self.assertEqual((r["state"], r["note"], bool(r.get("fatal"))), ("down", "blocked address", True), ips)
            self.assertEqual(sess.calls, [])                              # never connected
        async def boom(h): raise OSError("nxdomain")
        svc.resolve = boom; r = await svc.probe("https://nope.com")
        self.assertEqual((r["state"], r["note"]), ("down", "dns lookup failed"))

    async def test_wake_sequence_and_persistence(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, sess, svc = await self.env(fac); cfg.WAKE_TIMEOUT = 5
                m, _ = await svc.add(1, "https://a.com")
                sess.script["https://a.com"] = [asyncio.TimeoutError(), 503, 200]
                seen = []
                async def prog(att, r, secs): seen.append((att, r["state"]))
                res = await svc.wake(m, prog)
                self.assertEqual((res["ok"], res["woke"], res["attempts"]), (True, True, 3))
                self.assertEqual(seen, [(1, "sleeping"), (2, "sleeping")])
                s = await db.get(1, m["id"])
                for k in ("total", "ok", "wakes", "status"): self.assertEqual(s[k], m[k], k)
                self.assertEqual((s["wakes"], s["status"], s["logs"][-1]["k"]), (1, "up", "wake"))

    async def test_wake_already_awake_and_failures(self):
        _, sess, svc = await self.env()
        m = core.new_monitor(1, "https://a.com", temp=True)
        res = await svc.wake(m); self.assertEqual((res["ok"], res["woke"], m["wakes"]), (True, False, 0))
        sess.script["https://a.com"] = [503]
        res = await svc.wake(m); self.assertFalse(res["ok"]); self.assertEqual(m["status"], "sleeping")
        self.assertGreater(res["attempts"], 1)
        async def bad(*a): raise RuntimeError("ui broke")
        sess.script["https://a.com"] = [503, 200]
        self.assertTrue((await svc.wake(m, bad))["ok"])                    # failing progress callback is harmless
        HOSTS["evil.com"] = ["127.0.0.1"]; e = core.new_monitor(1, "https://evil.com", temp=True)
        res = await svc.wake(e); self.assertEqual((res["ok"], res["attempts"]), (False, 1))   # fatal → no retry loop

    async def test_add_rules(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, sess, svc = await self.env(fac)
                m, r = await svc.add(1, "a.com"); self.assertEqual(m["url"], "https://a.com"); self.assertEqual(r["state"], "up")
                self.assertEqual((await db.get(1, m["id"]))["total"], 1)
                for bad in ("", "localhost", "ftp://x.com", None, 7):
                    with self.assertRaises(core.UserError): await svc.add(1, bad)
                with self.assertRaises(core.UserError) as e: await svc.add(1, "https://a.com")
                self.assertIn("already", str(e.exception))
                await svc.add(2, "https://a.com")                                  # same link, other user → fine
                await svc.add(1, "https://b.com"); await svc.add(1, "https://c.com")
                with self.assertRaises(core.UserError) as e: await svc.add(1, "https://d.com")
                self.assertIn("limit", str(e.exception)); self.assertEqual(await db.count(1), 3)
                HOSTS["evil.com"] = ["127.0.0.1"]
                with self.assertRaises(core.UserError) as e: await svc.add(2, "https://evil.com")
                self.assertIn("not allowed", str(e.exception)); self.assertEqual(await db.count(2), 1)  # rolled back

    async def test_add_race_conditions(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, _, svc = await self.env(fac)
                res = await asyncio.gather(*[svc.add(1, "https://same.com") for _ in range(6)], return_exceptions=True)
                self.assertEqual(sum(1 for x in res if not isinstance(x, Exception)), 1)
                self.assertEqual(await db.count(1), 1)
                res = await asyncio.gather(*[svc.add(5, f"https://s{i}.com") for i in range(8)], return_exceptions=True)
                self.assertLessEqual(await db.count(5), cfg.MAX_MONITORS_PER_USER)
                self.assertTrue(all(isinstance(x, (core.UserError, tuple)) for x in res))

    async def test_controls_and_guard(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, _, svc = await self.env(fac)
                m, _ = await svc.add(1, "https://a.com")
                await svc.toggle_pause(m); self.assertTrue((await db.get(1, m["id"]))["paused"])
                await svc.toggle_pause(m); s = await db.get(1, m["id"]); self.assertFalse(s["paused"]); self.assertEqual(s["next_check"], 0)
                seen = []
                for _ in range(6): await svc.cycle_interval(m); seen.append((await db.get(1, m["id"]))["interval"])
                self.assertEqual(seen, [600, 900, 60, 120, 300, 600])
                async with svc.guard(m):
                    with self.assertRaises(core.UserError) as e:
                        async with svc.guard(m): pass
                    self.assertEqual(e.exception.status, 409)
                async with svc.guard(m): pass                                       # released afterwards
                await svc.delete(m)
                with self.assertRaises(core.UserError) as e: await svc.delete(m)
                self.assertEqual(e.exception.status, 404)


# ───────────────────────── mini app API ─────────────────────────
async def call(app, method, path, uid=None, body=None, query=None, init=None):
    handler = next(h for m, p, h in app.routes if (m, p) == (method, path))
    headers = {}
    if uid is not None: headers["X-Init-Data"] = make_init(uid)
    if init is not None: headers["X-Init-Data"] = init
    async def jsonf():
        if body is BAD: raise ValueError("not json")
        return body
    req = SimpleNamespace(headers=headers, query=query or {}, app=app, json=jsonf)
    h = handler
    for mw in reversed(app.middlewares): h = functools.partial(lambda r, mw, nxt: mw(r, nxt), mw=mw, nxt=h)
    try: resp = await h(req)
    except stubs.HTTPException as e: return e.status, None
    return resp.status, getattr(resp, "data", getattr(resp, "text", None))

class TestAPI(Base):
    async def test_auth_required(self):
        db, _, svc = await self.env(); app = api.build_app(svc)
        for method, path in [("GET", "/api/list"), ("POST", "/api/add"), ("POST", "/api/act"), ("GET", "/api/logs")]:
            self.assertEqual((await call(app, method, path, body={}))[0], 401)
            self.assertEqual((await call(app, method, path, init="user=%7B%22id%22%3A1%7D&hash=abc", body={}))[0], 401)
            self.assertEqual((await call(app, method, path, init=make_init(1, token="9:X"), body={}))[0], 401)
        self.assertEqual((await call(app, "GET", "/health"))[0], 200); self.assertEqual((await call(app, "GET", "/app"))[0], 200)

    async def test_full_flow_and_privacy(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, sess, svc = await self.env(fac); app = api.build_app(svc)
                st, a = await call(app, "POST", "/api/add", 1, {"url": "https://a.com"})
                self.assertEqual(st, 200); self.assertEqual(a["url"], "https://a.com")
                self.assertTrue({"owner", "_id", "logs", "temp"}.isdisjoint(a))
                self.assertEqual(len((await call(app, "GET", "/api/list", 1))[1]), 1)
                self.assertEqual((await call(app, "GET", "/api/list", 2))[1], [])
                before = await db.get(1, a["id"])
                for act in ("ping", "wake", "pause", "interval", "delete"):          # user 2 attacks user 1's monitor
                    st, d = await call(app, "POST", "/api/act", 2, {"id": a["id"], "act": act})
                    self.assertEqual(st, 404, act); self.assertNotIn("a.com", json.dumps(d))
                self.assertEqual((await call(app, "GET", "/api/logs", 2, query={"id": a["id"]}))[0], 404)
                self.assertEqual(await db.get(1, a["id"]), before)                    # nothing changed
                for evil in ({"$ne": None}, {"$gt": ""}, [a["id"]], 5, None):
                    st, _ = await call(app, "POST", "/api/act", 2, {"id": evil, "act": "delete"})
                    self.assertEqual(st, 400)
                self.assertEqual((await call(app, "GET", "/api/logs", 2, query={"id": "{'$ne': ''}"}))[0], 404)
                self.assertEqual((await call(app, "GET", "/api/logs", 1, query={"id": a["id"]}))[0], 200)
                st, d = await call(app, "POST", "/api/act", 1, {"id": a["id"], "act": "ping"}); self.assertEqual(d["result"]["state"], "up")
                st, d = await call(app, "POST", "/api/act", 1, {"id": a["id"], "act": "pause"}); self.assertTrue(d["monitor"]["paused"])
                st, d = await call(app, "POST", "/api/act", 1, {"id": a["id"], "act": "interval"}); self.assertEqual(d["monitor"]["interval"], 600)
                cfg.WAKE_TIMEOUT = 5; sess.script["https://a.com"] = [503, 200]
                st, d = await call(app, "POST", "/api/act", 1, {"id": a["id"], "act": "wake"})
                self.assertEqual((st, d["result"]["ok"], d["result"]["woke"]), (200, True, True))
                st, d = await call(app, "POST", "/api/act", 1, {"id": a["id"], "act": "delete"}); self.assertEqual(d, {"deleted": True})
                self.assertEqual((await call(app, "GET", "/api/list", 1))[1], [])

    async def test_bad_input(self):
        db, _, svc = await self.env(); app = api.build_app(svc)
        for body in (BAD, [], "x", 5, None):
            self.assertEqual((await call(app, "POST", "/api/add", 1, body))[0], 400, body)
            self.assertEqual((await call(app, "POST", "/api/act", 1, body))[0], 400, body)
        for url in (None, 123, "", "localhost", "http://169.254.169.254", {"a": 1}):
            self.assertEqual((await call(app, "POST", "/api/add", 1, {"url": url}))[0], 400, url)
        await call(app, "POST", "/api/add", 1, {"url": "https://a.com"})
        st, d = await call(app, "POST", "/api/add", 1, {"url": "https://a.com"}); self.assertEqual(st, 400); self.assertIn("already", d["error"])
        mid = (await call(app, "GET", "/api/list", 1))[1][0]["id"]
        for act in ("hack", None, "", "DELETE"): self.assertEqual((await call(app, "POST", "/api/act", 1, {"id": mid, "act": act}))[0], 400)
        self.assertEqual((await call(app, "POST", "/api/act", 1, {"act": "ping"}))[0], 400)
        self.assertEqual((await call(app, "GET", "/api/logs", 1))[0], 404)

    async def test_busy_and_server_error(self):
        db, _, svc = await self.env(); app = api.build_app(svc)
        _, a = await call(app, "POST", "/api/add", 1, {"url": "https://a.com"})
        svc.busy.add(a["id"])
        self.assertEqual((await call(app, "POST", "/api/act", 1, {"id": a["id"], "act": "wake"}))[0], 409)
        svc.busy.clear()
        async def boom(uid): raise RuntimeError("mongodb://user:secret@host exploded")
        db.list = boom
        st, d = await call(app, "GET", "/api/list", 1)
        self.assertEqual(st, 500); self.assertNotIn("secret", json.dumps(d))


# ───────────────────────── bot flow with fake Telegram ─────────────────────────
class FSent:
    def __init__(s, h, uid): s.h, s.uid, s.text, s.markup = h, uid, "", None
    async def edit_text(s, text, reply_markup=None):
        if s.h.fail_edit: raise stubs.TelegramBadRequest("message is not modified")
        s.text, s.markup = text, reply_markup; s.h.out.append(("edit", s.uid, text, reply_markup))

class FMsg(stubs.Message):
    def __init__(s, h, uid, text): s.h, s.text, s.from_user = h, text, SimpleNamespace(id=uid, first_name=f"User{uid}")
    async def answer(s, text, reply_markup=None):
        sent = FSent(s.h, s.from_user.id); sent.text, sent.markup = text, reply_markup
        s.h.screens[s.from_user.id] = sent; s.h.out.append(("answer", s.from_user.id, text, reply_markup)); return sent

class FCb(stubs.CallbackQuery):
    def __init__(s, h, uid, data):
        s.h, s.data, s.from_user = h, data, SimpleNamespace(id=uid, first_name=f"User{uid}")
        s.message = h.screens.setdefault(uid, FSent(h, uid))
    async def answer(s, text=None, show_alert=False): s.h.out.append(("cb", s.from_user.id, text, show_alert))

class Harness:
    def __init__(s, svc):
        s.svc, s.out, s.screens, s.fail_edit, s.expect_errors = svc, [], {}, False, False
        botmod.setup(svc, SimpleNamespace())
    async def feed(s, kind, ev):
        start = len(s.out)
        for rt, k, filters, fn in [(r, k, f, fn) for r in (botmod.router, admin_bot.router) for k, f, fn in r.handlers]:
            if k != kind or not all(f.resolve(ev) if isinstance(f, stubs.MF) else f.match(ev) for f in filters): continue
            async def call_(e, d, fn=fn): return await fn(e)
            h = call_
            for mw in reversed(rt.middlewares[kind]): h = (lambda mw, nxt: lambda e, d: mw(nxt, e, d))(mw, h)
            await h(ev, {}); break
        else: return False
        for kind_, uid, text, extra in s.out[start:]:
            if kind_ in ("answer", "edit"):
                assert BRAND in text, f"missing Dotxbrain branding: {text[:60]!r}"
                if not s.expect_errors: assert WRONG not in text, f"handler crashed: {text}"
        return True
    async def send(s, uid, text): return await s.feed("message", FMsg(s, uid, text))
    async def tap(s, uid, data):
        n = len(s.out); await s.feed("callback_query", FCb(s, uid, data)); return s.out[n:]
    def last(s, uid): return next(t for k, u, t, _ in reversed(s.out) if u == uid and k in ("answer", "edit"))
    def alerts(s, uid): return [t for k, u, t, a in s.out if u == uid and k == "cb" and a]
    def markup(s, uid): return next(m for k, u, _, m in reversed(s.out) if u == uid and k in ("answer", "edit") and m)
    def buttons(s, uid): return [b for row in s.markup(uid).inline_keyboard for b in row]
    def cb_for(s, uid, word): return next(b.callback_data for b in s.buttons(uid) if b.callback_data and b.callback_data.startswith(word))

class TestBot(Base):
    async def setup_user(self, factory=BACKENDS[0][1], uid=1, url="https://a.onrender.com"):
        db, sess, svc = await self.env(factory); h = Harness(svc)
        await h.send(uid, url); mon = (await db.list(uid))[0]; return db, sess, svc, h, mon

    async def test_start_branding_and_buttons(self):
        db, _, svc = await self.env(); h = Harness(svc)
        await h.send(1, "/start"); t = h.last(1)
        self.assertIn(BRAND, t); self.assertIn("ᴜᴘᴛɪᴍᴇ ᴘʀᴏ", t); self.assertIn("ᴘʀɪᴠᴀᴛᴇ", t)
        self.assertTrue(any(b.web_app and b.web_app.url == "https://dx.onrender.com/app" for b in h.buttons(1)))
        self.assertIn(1, db.users)
        cfg.BRAND_LINK = "https://t.me/dotxbrain"; await h.send(1, "/start")
        self.assertTrue(any(b.url == "https://t.me/dotxbrain" and BRAND in b.text for b in h.buttons(1)))
        cfg.BASE_URL = ""; await h.send(1, "/start"); self.assertFalse(any(b.web_app for b in h.buttons(1)))

    async def test_add_flows(self):
        db, sess, svc, h, mon = await self.setup_user()
        self.assertIn("a.onrender.com", h.last(1)); self.assertIn("ᴀᴡᴀᴋᴇ", h.last(1))
        self.assertTrue(any(b.callback_data == f"wake:{mon['id']}" for b in h.buttons(1)))
        n = len(h.out); await h.send(1, "hello there"); self.assertEqual(len(h.out), n)          # ignored chatter
        await h.tap(1, "add"); self.assertIn(1, botmod.WAITING)
        await h.send(1, "not a link!!"); self.assertIn(core.sc("valid link"), h.last(1))
        self.assertIn(1, botmod.WAITING)
        await h.send(1, "b.onrender.com"); self.assertEqual(await db.count(1), 2); self.assertNotIn(1, botmod.WAITING)
        await h.send(1, "https://b.onrender.com"); self.assertIn("ᴀʟʀᴇᴀᴅʏ", h.last(1))
        sess.script["https://c.com"] = [503]; await h.send(1, "c.com"); self.assertIn("ꜱʟᴇᴇᴘɪɴɢ", h.last(1))
        await h.send(1, "d.com"); self.assertIn("ʟɪᴍɪᴛ", h.last(1)); self.assertEqual(await db.count(1), 3)
        HOSTS["evil.com"] = ["127.0.0.1"]; await h.send(2, "evil.com"); self.assertIn("ɴᴏᴛ ᴀʟʟᴏᴡᴇᴅ", h.last(2)); self.assertEqual(await db.count(2), 0)

    async def test_full_tour(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, sess, svc, h, mon = await self.setup_user(fac); i = mon["id"]; cfg.WAKE_TIMEOUT = 5
                await h.tap(1, "list"); self.assertIn(f"m:{i}", [b.callback_data for b in h.buttons(1)])
                await h.tap(1, f"m:{i}"); self.assertIn("ᴍᴏɴɪᴛᴏʀ ᴘᴀɴᴇʟ", h.last(1))
                await h.tap(1, f"ping:{i}"); self.assertIn(core.sc("ping successful"), h.last(1))
                sess.script[mon["url"]] = [503]; await h.tap(1, f"ping:{i}")
                self.assertIn("ꜱʟᴇᴇᴘɪɴɢ", h.last(1)); self.assertEqual(h.cb_for(1, "wake:"), f"wake:{i}")
                sess.script[mon["url"]] = [503, 503, 200]; await h.tap(1, f"wake:{i}")
                self.assertIn("ᴡᴀᴋᴇ-ᴜᴘ", h.last(1)); self.assertTrue(any("ᴡᴀᴋɪɴɢ ᴜᴘ" in t for k, u, t, _ in h.out if k == "edit"))
                sess.script[mon["url"]] = [200]; await h.tap(1, f"wake:{i}"); self.assertIn("ᴀʟʀᴇᴀᴅʏ ᴀᴡᴀᴋᴇ", h.last(1))
                sess.script[mon["url"]] = [503]; await h.tap(1, f"wake:{i}"); self.assertIn("ᴄᴏᴜʟᴅ ɴᴏᴛ ᴡᴀᴋᴇ", h.last(1))
                await h.tap(1, f"logs:{i}"); self.assertIn(core.sc("smart logs"), h.last(1)); self.assertIn("🏓", h.last(1))
                await h.tap(1, f"int:{i}"); self.assertIn(f"seti:{i}:600", [b.callback_data for b in h.buttons(1)])
                await h.tap(1, f"seti:{i}:600"); self.assertEqual((await db.get(1, i))["interval"], 600)
                await h.tap(1, f"pause:{i}"); self.assertTrue((await db.get(1, i))["paused"]); self.assertIn("▶️", h.markup(1).inline_keyboard[3][0].text)
                await h.tap(1, f"pause:{i}"); self.assertFalse((await db.get(1, i))["paused"])
                await h.tap(1, "stats"); self.assertIn(core.sc("monitors"), h.last(1)); await h.tap(1, "help"); await h.tap(1, "home")
                await h.tap(1, f"del:{i}"); self.assertIsNotNone(await db.get(1, i))                  # confirm first
                await h.tap(1, f"delok:{i}"); self.assertIsNone(await db.get(1, i)); self.assertIn("ɴᴏᴛʜɪɴɢ ʜᴇʀᴇ", h.last(1))

    async def test_privacy_between_users(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, sess, svc, h, mon = await self.setup_user(fac, 1, "https://secret-one.com"); i = mon["id"]
                before = await db.get(1, i)
                await h.tap(2, "list"); self.assertIn("ɴᴏᴛʜɪɴɢ ʜᴇʀᴇ", h.last(2))
                await h.tap(2, "stats"); self.assertNotIn("secret-one", h.last(2))
                for action in ("m", "ping", "wake", "logs", "int", "pause", "del", "delok", "mute", "ren"):
                    out = await h.tap(2, f"{action}:{i}")
                    self.assertTrue(any(k == "cb" and a for k, _, _, a in out), action)          # "not found" alert only
                    self.assertFalse(any(k in ("edit", "answer") for k, *_ in out), action)
                out = await h.tap(2, f"seti:{i}:60")                                             # someone else's monitor
                self.assertTrue(any(k == "cb" and a for k, _, _, a in out)); self.assertEqual((await db.get(1, i))["interval"], 300)
                for evil in ("m:", "wake:", "ping:zzz", "m:{'$ne': 1}", "del:" + "x" * 500, "m:%s:extra" % i):
                    await h.tap(2, evil)
                self.assertEqual(await db.get(1, i), before)
                self.assertFalse(any("secret-one" in t for k, u, t, _ in h.out if u == 2 and k in ("edit", "answer")))
                await h.send(2, "https://secret-one.com"); self.assertEqual(await db.count(2), 1)   # own independent copy
                await h.tap(1, "list"); self.assertEqual(len(h.markup(1).inline_keyboard), 3)
                self.assertFalse(await h.feed("callback_query", FCb(h, 1, "totally-unknown")))   # unknown button → ignored

    async def test_quick_commands(self):
        db, sess, svc = await self.env(); h = Harness(svc)
        await h.send(1, "/ping https://a.com"); self.assertIn(core.sc("ping result"), h.last(1))
        await h.send(1, "/wake https://a.com"); self.assertIn(core.sc("slow down"), h.last(1))                   # cooldown
        botmod.LAST_QUICK.clear(); sess.script["https://a.com"] = [503, 200]; cfg.WAKE_TIMEOUT = 5
        await h.send(1, "/wake https://a.com"); self.assertIn(core.sc("wake result"), h.last(1))
        for cmd in ("/ping", "/ping localhost", "/wake http://169.254.169.254", "/ping a b"):
            botmod.LAST_QUICK.clear(); await h.send(1, cmd); self.assertIn("⚠️", h.last(1), cmd)
        self.assertEqual(await db.count(1), 0)                                                        # never stored

    async def test_busy_edit_errors_and_crashes(self):
        db, sess, svc, h, mon = await self.setup_user(); i = mon["id"]
        svc.busy.add(i); out = await h.tap(1, f"wake:{i}"); self.assertIn("ᴀʟʀᴇᴀᴅʏ ᴡᴀᴋɪɴɢ", out[-1][2]); svc.busy.clear()
        h.fail_edit = True; await h.tap(1, "list"); await h.tap(1, f"wake:{i}"); h.fail_edit = False   # swallowed
        h.expect_errors = True
        async def boom(*a): raise RuntimeError("db exploded")
        real = db.list; db.list = boom
        out = await h.tap(1, "list"); self.assertIn(WRONG, out[-1][2]); db.list = real
        real_add = svc.add; svc.add = boom; await h.send(1, "zzz.com"); self.assertIn(WRONG, h.last(1)); svc.add = real_add

    async def test_all_keyboards_are_valid_telegram_buttons(self):
        db, sess, svc, h, mon = await self.setup_user()
        for data in ("home", "help", "add", "list", "stats", f"m:{mon['id']}", f"del:{mon['id']}"):
            await h.tap(1, data)
            for b in h.buttons(1):
                self.assertEqual(sum(x is not None for x in (b.callback_data, b.url, b.web_app)), 1)


# ───────────────────────── background worker ─────────────────────────
class FBot:
    def __init__(s, fail=False): s.sent, s.fail = [], fail
    async def send_message(s, uid, text):
        if s.fail: raise RuntimeError("bot was blocked by the user")
        s.sent.append((uid, text))

class TestWorker(Base):
    async def mk(self, url="https://a.com"):
        db, sess, svc = await self.env(); m, _ = await svc.add(1, url); return db, sess, svc, await db.get(1, m["id"])

    async def test_alert_lifecycle(self):
        db, sess, svc, m = await self.mk(); bot = FBot(); u = "https://a.com"
        await worker.run_check(svc, bot, m); self.assertEqual(bot.sent, []); self.assertEqual(m["logs"][-1]["k"], "auto")
        sess.script[u] = [503]; await worker.run_check(svc, bot, m)                     # sleeps, cannot wake
        self.assertEqual(len(bot.sent), 1); self.assertIn(core.sc("site is down"), bot.sent[0][1]); self.assertIn(BRAND, bot.sent[0][1])
        await worker.run_check(svc, bot, m); self.assertEqual(len(bot.sent), 1)         # no spam while still down
        sess.script[u] = [200]; await worker.run_check(svc, bot, m)
        self.assertEqual(len(bot.sent), 2); self.assertIn(core.sc("back online"), bot.sent[1][1])
        sess.script[u] = [503, 200]; await worker.run_check(svc, bot, m)                # auto wake works
        self.assertIn(core.sc("auto wake-up done"), bot.sent[-1][1]); self.assertEqual(bot.sent[-1][0], 1)
        cfg.AUTO_WAKE = False; sess.script[u] = [500]; n = len(bot.sent); await worker.run_check(svc, bot, m)
        self.assertEqual(len(bot.sent), n + 1)

    async def test_failures_are_contained(self):
        db, sess, svc, m = await self.mk()
        sess.script["https://a.com"] = [503]; await worker.run_check(svc, FBot(fail=True), m)   # blocked bot: no crash
        svc.busy.add(m["id"]); total = m["total"]; await worker.run_check(svc, FBot(), m); self.assertEqual(m["total"], total)
        svc.busy.clear()
        async def boom(*a, **k): raise RuntimeError("network down")
        svc.probe = boom; await worker.run_check(svc, FBot(), m)

    async def test_tick_selects_due_monitors(self):
        db, sess, svc, a = await self.mk("https://a.com")
        b, _ = await svc.add(1, "https://b.com"); c, _ = await svc.add(1, "https://c.com")
        await svc.toggle_pause(b)                                                             # paused
        await db.set_fields(1, a["id"], {"next_check": 0}); await db.set_fields(1, c["id"], {"next_check": int(time.time()) + 999})
        tasks = await worker.tick(svc, FBot()); self.assertEqual(len(tasks), 1); await asyncio.gather(*tasks)
        self.assertEqual((await db.get(1, a["id"]))["logs"][-1]["k"], "auto")
        self.assertEqual(len((await db.get(1, c["id"]))["logs"]), 1)


# ───────────────────────── v3 features: admin panel, mute, rename, bans, outages ─────────────────────────
class TestFeatures(Base):
    async def test_outage_tracking_and_helpers(self):
        db, sess, svc = await self.env(); m, _ = await svc.add(1, "https://a.com")
        sess.script["https://a.com"] = [503]; await svc.ping(m)
        self.assertEqual(m["outages"], 1); self.assertGreater(m["down_since"], 0)
        await svc.ping(m); self.assertEqual(m["outages"], 1)                              # same outage, not counted twice
        m["down_since"] -= 125; sess.script["https://a.com"] = [200]; await svc.ping(m)
        self.assertEqual(m["down_since"], 0); self.assertGreaterEqual(m["last_outage"], 125)
        self.assertEqual(core.dur(125), "2m 5s"); self.assertEqual(core.dur(7260), "2h 1m")
        self.assertEqual(core.spark([1, None, 9]), "▁✖█"); self.assertEqual(core.spark([]), "—")
        self.assertIn(core.sc("outages"), templates.card(m))

    async def test_rename_mute_interval_and_alert_rules(self):
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1]); i = mon["id"]
        await h.tap(1, f"ren:{i}"); self.assertEqual(botmod.PENDING[1], ("rename", i))
        await h.send(1, "My <b>API</b>"); self.assertEqual((await db.get(1, i))["name"], "My bAPI/b")
        await h.tap(1, f"mute:{i}"); self.assertTrue((await db.get(1, i))["muted"])
        m = await db.get(1, i); sess.script[m["url"]] = [503]; bot = FBot()
        await worker.run_check(svc, bot, m); self.assertEqual(bot.sent, [])                # muted → silent
        await h.tap(1, f"mute:{i}"); m = await db.get(1, i); m["status"] = "up"
        await h.tap(1, "notif"); self.assertFalse((await db.get_user(1))["notify"])        # global alerts off
        await worker.run_check(svc, bot, m); self.assertEqual(bot.sent, [])
        with self.assertRaises(core.UserError): await svc.set_interval(m, 7)
        await svc.set_interval(m, 900); self.assertEqual((await db.get(1, i))["interval"], 900)
        with self.assertRaises(core.UserError): await svc.rename(m, "  <>  ")

    async def test_check_all_and_commands(self):
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1])
        await h.send(1, "b.com"); await h.tap(1, "chk"); self.assertIn(core.sc("check all"), h.last(1))
        out = await h.tap(1, "chk"); self.assertTrue(any(k == "cb" and a for k, _, _, a in out))   # cooldown
        for cmd in ("/list", "/stats", "/settings", "/help"): await h.send(1, cmd); self.assertIn(BRAND, h.last(1))

    async def test_admin_access_and_dashboard(self):
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1], uid=5)
        n = len(h.out); await h.send(5, "/admin")
        self.assertTrue(any(k == "answer" and core.sc("admins only") in t for k, _, t, _ in h.out[n:]))
        out = await h.tap(5, "adm:u:0"); self.assertTrue(any(k == "cb" and a for k, _, _, a in out))   # buttons blocked too
        await h.send(99, "/admin"); self.assertIn(core.sc("admin panel"), h.last(99)); self.assertIn("1", h.last(99))
        for cb in ("adm:u:0", "adm:m:0", "adm:set", "adm"): await h.tap(99, cb); self.assertIn(BRAND, h.last(99))
        await h.tap(99, "adm:u:0"); await h.tap(99, h.cb_for(99, "adm:ud:")); self.assertIn("5", h.last(99))

    async def test_admin_ban_limit_settings_broadcast(self):
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1], uid=5); h.svc.last_broadcast = None
        await h.tap(99, "adm:ban:5"); self.assertIn(5, svc.banned); self.assertTrue((await db.get_user(5))["banned"])
        n = len(h.out); await h.send(5, "/start")
        self.assertTrue(any(core.sc("banned") in t for k, _, t, _ in h.out[n:]))
        out = await h.tap(5, "list"); self.assertTrue(any(k == "cb" and a for k, _, _, a in out))
        await svc.load_state(); self.assertIn(5, svc.banned)                              # survives restart
        await h.tap(99, "adm:unban:5"); self.assertNotIn(5, svc.banned)
        await h.tap(99, "adm:lim:5"); await h.send(99, "1"); self.assertEqual(await svc.user_limit(5), 1)
        with self.assertRaises(core.UserError): await svc.add(5, "https://two.com")       # per-user limit enforced
        await h.tap(99, "adm:lim:5"); await h.send(99, "0"); self.assertEqual(await svc.user_limit(5), cfg.MAX_MONITORS_PER_USER)
        await h.tap(99, "adm:tg:maintenance"); self.assertTrue(svc.setting("maintenance"))
        n = len(h.out); await h.send(5, "/start"); self.assertTrue(any(core.sc("maintenance") in t for k, _, t, _ in h.out[n:]))
        await h.send(99, "/start"); self.assertIn(BRAND, h.last(99))                      # admins are never locked out
        await h.tap(99, "adm:tg:maintenance"); await h.tap(99, "adm:tg:signups"); self.assertFalse(svc.setting("signups"))
        with self.assertRaises(core.UserError): await svc.register(777, "new")
        await h.tap(99, "adm:tg:auto_wake"); self.assertFalse(svc.setting("auto_wake"))
        await h.tap(99, "adm:lm"); self.assertEqual(svc.setting("max_monitors"), 5)
        s2 = core.Service(db, sess); await s2.load_state(); self.assertEqual(s2.setting("max_monitors"), 5)   # persisted
        bot = FBot(); h.svc.db = db; botmod.setup(svc, bot)
        await h.tap(99, "adm:bc"); await h.send(99, "Hello <b>all</b>"); await h.tap(99, "adm:bcok")
        self.assertTrue(any(uid == 5 for uid, _ in bot.sent)); self.assertIn("ᴅᴏᴛxʙʀᴀɪɴ", bot.sent[0][1])
        await h.tap(99, "adm:pgok:5"); self.assertEqual(await db.count(5), 0)

    async def test_admin_monitor_controls(self):
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1], uid=5); i = mon["id"]
        await h.tap(99, f"adm:md:{i}"); self.assertIn("5", h.last(99))
        await h.tap(99, f"adm:mt:{i}"); self.assertTrue((await db.get(5, i))["paused"])
        await h.tap(99, f"adm:mp:{i}"); await h.tap(99, f"adm:mw:{i}")
        await h.tap(99, f"adm:mx:{i}"); self.assertIsNotNone(await db.get(5, i))
        await h.tap(99, f"adm:mxok:{i}"); self.assertIsNone(await db.get(5, i))

    async def test_api_admin_routes(self):
        for name, fac in BACKENDS:
            with self.subTest(backend=name):
                db, sess, svc = await self.env(fac); bot = FBot(); app = api.build_app(svc, bot)
                m, _ = await svc.add(5, "https://a.com"); await svc.register(5, "Raj")
                routes = [("GET", "/api/admin/overview"), ("GET", "/api/admin/users"), ("GET", "/api/admin/monitors"),
                          ("POST", "/api/admin/user"), ("POST", "/api/admin/monitor"), ("POST", "/api/admin/settings"),
                          ("POST", "/api/admin/broadcast")]
                for method, path in routes:
                    self.assertEqual((await call(app, method, path, body={}))[0], 401)             # no auth
                    self.assertEqual((await call(app, method, path, uid=5, body={}))[0], 403, path)   # normal user
                st, me = await call(app, "GET", "/api/me", uid=5); self.assertEqual((st, me["admin"]), (200, False))
                st, me = await call(app, "GET", "/api/me", uid=99); self.assertTrue(me["admin"])
                st, ov = await call(app, "GET", "/api/admin/overview", uid=99); self.assertEqual((st, ov["monitors"]), (200, 1))
                st, us = await call(app, "GET", "/api/admin/users", uid=99); self.assertEqual(us["users"][0]["monitors"], 1)
                st, r = await call(app, "POST", "/api/admin/user", uid=99, body={"uid": 5, "act": "ban"}); self.assertTrue(r["banned"])
                self.assertEqual((await call(app, "GET", "/api/list", uid=5))[0], 403)             # banned user is locked out
                await call(app, "POST", "/api/admin/user", uid=99, body={"uid": 5, "act": "unban"})
                self.assertEqual((await call(app, "POST", "/api/admin/user", uid=99, body={"uid": 99, "act": "ban"}))[0], 400)
                self.assertEqual((await call(app, "POST", "/api/admin/user", uid=99, body={"uid": "5", "act": "ban"}))[0], 400)
                st, r = await call(app, "POST", "/api/admin/user", uid=99, body={"uid": 5, "act": "limit", "value": 2}); self.assertEqual(r["limit"], 2)
                st, r = await call(app, "POST", "/api/admin/settings", uid=99, body={"key": "maintenance", "value": True}); self.assertTrue(r["maintenance"])
                self.assertEqual((await call(app, "GET", "/api/list", uid=5))[0], 503)
                self.assertEqual((await call(app, "GET", "/api/list", uid=99))[0], 200)
                self.assertEqual((await call(app, "POST", "/api/admin/settings", uid=99, body={"key": "evil", "value": 1}))[0], 400)
                self.assertEqual((await call(app, "POST", "/api/admin/settings", uid=99, body={"key": "max_monitors", "value": 9999}))[0], 400)
                await call(app, "POST", "/api/admin/settings", uid=99, body={"key": "maintenance", "value": False})
                st, r = await call(app, "POST", "/api/admin/monitor", uid=99, body={"id": m["id"], "act": "pause"}); self.assertTrue(r["monitor"]["paused"])
                st, r = await call(app, "POST", "/api/admin/monitor", uid=99, body={"id": m["id"], "act": "ping"}); self.assertEqual(r["result"]["state"], "up")
                st, r = await call(app, "POST", "/api/admin/broadcast", uid=99, body={"text": "hi"}); self.assertTrue(r["started"])
                await asyncio.sleep(0.2); self.assertTrue(bot.sent)
                st, r = await call(app, "POST", "/api/admin/monitor", uid=99, body={"id": m["id"], "act": "delete"}); self.assertTrue(r["deleted"])

    async def test_api_user_features(self):
        db, sess, svc = await self.env(); app = api.build_app(svc); m, _ = await svc.add(1, "https://a.com")
        st, r = await call(app, "POST", "/api/act", uid=1, body={"id": m["id"], "act": "rename", "value": "Prod"}); self.assertEqual(r["monitor"]["name"], "Prod")
        st, r = await call(app, "POST", "/api/act", uid=1, body={"id": m["id"], "act": "mute"}); self.assertTrue(r["monitor"]["muted"])
        st, r = await call(app, "POST", "/api/act", uid=1, body={"id": m["id"], "act": "interval", "value": 600}); self.assertEqual(r["monitor"]["interval"], 600)
        self.assertEqual((await call(app, "POST", "/api/act", uid=1, body={"id": m["id"], "act": "interval", "value": 5}))[0], 400)
        self.assertIn("spark", r["monitor"]); self.assertIn("avg_ms", r["monitor"])
        self.assertEqual((await call(app, "POST", "/api/act", uid=2, body={"id": m["id"], "act": "rename", "value": "x"}))[0], 404)
        st, r = await call(app, "POST", "/api/prefs", uid=1, body={"notify": False}); self.assertFalse((await db.get_user(1))["notify"])
        self.assertEqual((await call(app, "POST", "/api/prefs", uid=1, body={"notify": "no"}))[0], 400)
        st, r = await call(app, "POST", "/api/checkall", uid=1, body={}); self.assertEqual((st, r["up"]), (200, 1))

    async def test_render_loading_page_counts_as_sleeping(self):
        db, sess, svc = await self.env(); sess.script["https://a.com"] = [(200, b"<title>Render - Application loading</title>")]
        r = await svc.probe("https://a.com"); self.assertEqual(r["state"], "sleeping")
        sess.script["https://b.com"] = [(200, b"INCOMING HTTP REQUEST DETECTED ...")]
        self.assertEqual((await svc.probe("https://b.com"))["state"], "sleeping")

    async def test_render_to_render_hint(self):
        self.assertTrue(templates.render_to_render("https://other.onrender.com"))
        self.assertFalse(templates.render_to_render("https://example.com"))
        self.assertFalse(templates.render_to_render("https://dx.onrender.com"))              # the bot's own address
        cfg.BASE_URL = "https://my-bot.herokuapp.com"; self.assertFalse(templates.render_to_render("https://other.onrender.com"))
        cfg.BASE_URL = "https://dx.onrender.com"
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1], url="https://other.onrender.com"); i = mon["id"]
        cfg.GH_TOKEN = ""; cfg.WAKE_TIMEOUT = 0.1; sess.script[mon["url"]] = [502]; await h.tap(1, f"wake:{i}")
        self.assertIn(core.sc("cannot wake another render site"), h.last(1))
        self.assertIn("kick(", read("webapp/index.html")); self.assertIn("WAKE_URLS", read(".github/workflows/keepalive.yml"))

    async def test_github_wake_dispatch(self):
        db, sess, svc, h, mon = await TestBot.setup_user(self, BACKENDS[0][1], url="https://other.onrender.com"); i = mon["id"]
        cfg.GH_TOKEN, cfg.GH_REPO, cfg.GH_BRANCH = "ghp_test", "me/repo", "main"; cfg.WAKE_TIMEOUT = 0.1
        sess.script[mon["url"]] = [502]; await h.tap(1, f"wake:{i}")
        self.assertEqual(len(sess.posts), 1); url, kw = sess.posts[0]
        self.assertTrue(url.endswith("/repos/me/repo/actions/workflows/wake.yml/dispatches"))
        self.assertEqual(kw["json"], {"ref": "main", "inputs": {"url": "https://other.onrender.com"}})
        self.assertEqual(kw["headers"]["Authorization"], "Bearer ghp_test")
        self.assertIn(core.sc("wake request sent through github"), h.last(1))
        await h.tap(1, f"wake:{i}"); self.assertEqual(len(sess.posts), 1)                  # throttled: not spammed
        await svc.gh_wake("https://example.com"); self.assertEqual(len(sess.posts), 1)       # never for non-Render links
        svc._gh_last.clear(); sess.post_status = 401; self.assertFalse(await svc.gh_wake(mon["url"]))   # bad token → no crash
        cfg.GH_TOKEN = ""; svc._gh_last.clear(); sess.posts.clear(); self.assertFalse(await svc.gh_wake(mon["url"])); self.assertEqual(sess.posts, [])
        wf = read(".github/workflows/wake.yml"); self.assertIn("workflow_dispatch", wf); self.assertIn("onrender", wf)
        self.assertNotIn("${{ inputs.url }}\n          run", wf); self.assertIn("URL: ${{ inputs.url }}", wf)   # no shell injection

    async def test_many_sites_sleeping_at_once(self):
        core.GH_SPACING = 0.01
        db, sess, svc = await self.env(); cfg.GH_TOKEN, cfg.GH_REPO = "ghp_test", "me/repo"; cfg.WAKE_TIMEOUT = 0.2
        ms = []
        for n in "abc":
            m, _ = await svc.add(1, f"https://{n}.onrender.com"); ms.append(m); sess.script[m["url"]] = [502]
        results = await asyncio.gather(*(svc.wake(m) for m in ms))
        sent = sorted(kw["json"]["inputs"]["url"] for _, kw in sess.posts)
        self.assertEqual(sent, [f"https://{n}.onrender.com" for n in "abc"])           # one workflow run per site, none lost
        self.assertTrue(all(r["gh"] for r in results))
        sess.script["https://b.onrender.com"] = [502, 200]; sess.posts.clear()           # one site wakes, the others keep failing
        r = await svc.wake(ms[1]); self.assertTrue(r["ok"] and r["woke"])
        wf = read(".github/workflows/wake.yml"); self.assertNotIn("concurrency", wf)      # runs in parallel, never queued behind each other

    async def test_heartbeat_reports_sleep_gap(self):
        db, sess, svc = await self.env(); bot = FBot()
        await db.save_setting("heartbeat", int(time.time()) - 1800); await svc.load_state()      # last seen 30 min ago
        task = asyncio.create_task(worker.heartbeat(svc, bot)); await asyncio.sleep(0.05); task.cancel()
        self.assertEqual([u for u, _ in bot.sent], [99]); self.assertIn(core.sc("bot was asleep"), bot.sent[0][1])
        self.assertIn("30m", bot.sent[0][1]); self.assertGreater((await db.load_settings())["heartbeat"], time.time() - 5)
        bot2 = FBot(); svc.settings["heartbeat"] = int(time.time()) - 30                          # short gap → no noise
        t2 = asyncio.create_task(worker.heartbeat(svc, bot2)); await asyncio.sleep(0.05); t2.cancel(); self.assertEqual(bot2.sent, [])
        self.assertLess(worker.PING_EVERY, 600)


# ───────────────────────── startup wiring ─────────────────────────
class TestMain(Base):
    async def run_main(self):
        stubs.Bot.instances.clear()
        await asyncio.wait_for(mainmod.main(), 5)
        for t in asyncio.all_tasks() - {asyncio.current_task()}: t.cancel()
        return stubs.Bot.instances[-1]

    async def test_missing_token_and_bad_mongo(self):
        cfg.BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
        with self.assertRaises(SystemExit) as e: await mainmod.main()
        self.assertIn("BOT_TOKEN", str(e.exception))
        for bad in (None, ""):                       # the original crash: token was None → TypeError
            cfg.BOT_TOKEN = bad
            with self.assertRaises(SystemExit) as e: await mainmod.main()
            self.assertIn("BOT_TOKEN", str(e.exception))
        cfg.BOT_TOKEN = "123:ABC"; cfg.MONGO_URI = "mongodb://bad-host"
        with self.assertRaises(SystemExit) as e: await mainmod.main()
        self.assertIn("MongoDB", str(e.exception))

    async def test_startup_ok_memory_and_mongo(self):
        for uri in ("", "mongodb://fake"):
            cfg.MONGO_URI = uri; bot = await self.run_main()
            calls = {c[0]: c for c in bot.calls}
            for need in ("set_my_commands", "set_my_description", "set_my_short_description", "set_chat_menu_button", "delete_webhook"):
                self.assertIn(need, calls, (uri, need))
            self.assertIn("Dotxbrain", calls["set_my_description"][1][0]); self.assertIn("Dotxbrain", calls["set_my_short_description"][1][0])
            self.assertEqual(calls["set_chat_menu_button"][2]["menu_button"].web_app.url, "https://dx.onrender.com/app")
            self.assertTrue(bot.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
