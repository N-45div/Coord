"""Black-box client helpers for the tablekeeper stage-3 verifier suite.

Every expected value in this suite comes from the stage-1..3 specifications
(kickoff/tablekeeper/spec/stage-1.md, stage-2.md, stage-3.md) and the requirements ledger
(evidence/ledger/ledger.md). Nothing here is derived from product source or
product output. The product is reached only through HTTP.
"""
import copy
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

BASE_URL = os.environ.get("TK_BASE_URL", "http://127.0.0.1:18282").rstrip("/")
SECOND_BASE_URL = os.environ.get("TK_SECOND_BASE_URL", "").rstrip("/")
REQ_TIMEOUT = 5.0  # spec §2: per-request timeout
CTL_TIMEOUT = 10.0  # spec §2/§10: reset, import, export
_NO = object()
_AUTO = object()


def new_key():
    return "k-" + uuid.uuid4().hex


class R:
    """A captured HTTP response."""

    def __init__(self, resp, elapsed):
        self.status = resp.status_code
        self.headers = resp.headers
        self.content = resp.content
        self.text = resp.text
        self.elapsed = elapsed
        try:
            self.json = resp.json() if resp.content else None
        except ValueError:
            self.json = None
        self.method = resp.request.method
        self.url = str(resp.request.url)

    def __repr__(self):
        return f"<{self.method} {self.url} -> {self.status} {self.text[:400]!r}>"


class Api:
    def __init__(self, base=None):
        self.base = (base or BASE_URL).rstrip("/")
        self.c = httpx.Client(base_url=self.base, timeout=REQ_TIMEOUT)

    def close(self):
        self.c.close()

    def call(self, method, path, *, token=None, body=_NO, raw=None, key=None,
             headers=None, params=None, timeout=REQ_TIMEOUT):
        h = {}
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        if key is not None:
            h["Idempotency-Key"] = key
        content = None
        if raw is not None:
            content = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            h["Content-Type"] = "application/json; charset=utf-8"
        elif body is not _NO:
            content = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json; charset=utf-8"
        if headers:
            h.update(headers)
        t0 = time.monotonic()
        resp = self.c.request(method, path, content=content, headers=h, params=params, timeout=timeout)
        return R(resp, time.monotonic() - t0)

    # --- test control (spec §3.3, §10) -------------------------------------------------
    def reset(self, fixture):
        r = self.call("POST", "/_test/reset", body=fixture, timeout=CTL_TIMEOUT)
        assert r.status == 204, f"reset failed: {r!r}"
        return r

    def export(self):
        r = self.call("GET", "/_test/export", timeout=CTL_TIMEOUT)
        expect(r, 200)
        return r.json

    def import_(self, obj=_NO, raw=None):
        return self.call("POST", "/_test/import", body=obj, raw=raw, timeout=CTL_TIMEOUT)

    # --- auth (spec §6) ----------------------------------------------------------------
    def signup(self, email, password, display_name="Someone", **extra):
        body = {"email": email, "password": password, "display_name": display_name, **extra}
        return self.call("POST", "/auth/signup", body=body)

    def login(self, email, password, **extra):
        return self.call("POST", "/auth/login", body={"email": email, "password": password, **extra})

    def token(self, email, password):
        r = self.login(email, password)
        expect(r, 200)
        return r.json["token"]

    # --- reservations (spec §8, §11) ---------------------------------------------------
    def create(self, token, body=_NO, key=_AUTO, raw=None):
        if key is _AUTO:
            key = new_key()
        return self.call("POST", "/reservations", token=token, body=body, key=key, raw=raw)

    def book(self, token, rid, tid, local, party=2, key=_AUTO):
        r = self.create(token, {"restaurant_id": rid, "table_id": tid,
                                "starts_at_local": local, "party_size": party}, key=key)
        expect(r, 201)
        return r.json

    def list(self, token):
        r = self.call("GET", "/reservations", token=token)
        expect(r, 200)
        assert isinstance(r.json, dict) and isinstance(r.json.get("reservations"), list), r
        return r.json["reservations"]

    def get(self, token, ref):
        return self.call("GET", f"/reservations/{quote(ref, safe='')}", token=token)

    def get_ok(self, token, ref):
        r = self.get(token, ref)
        expect(r, 200)
        return r.json

    def cancel(self, token, ref):
        return self.call("POST", f"/reservations/{quote(ref, safe='')}/cancel", token=token)

    def patch(self, token, ref, body=_NO, raw=None):
        return self.call("PATCH", f"/reservations/{quote(ref, safe='')}", token=token, body=body, raw=raw)

    def moves(self, token, body=_NO, key=_AUTO, raw=None):
        if key is _AUTO:
            key = new_key()
        return self.call("POST", "/reservation-moves", token=token, body=body, key=key, raw=raw)

    # --- stage 3 ----------------------------------------------------------------------------
    def history(self, token, ref):
        return self.call("GET", f"/reservations/{quote(ref, safe='')}/history", token=token)

    def entries(self, token, ref):
        r = self.history(token, ref)
        expect(r, 200)
        assert r.json.get("reference") == ref, r
        return r.json["entries"]

    def decision(self, token, ref):
        return self.call("GET", f"/reservations/{quote(ref, safe='')}/decision", token=token)

    def publish(self, token, rid, pol, key=_AUTO):
        if key is _AUTO:
            key = new_key()
        return self.call("POST", f"/restaurants/{quote(rid, safe='')}/policies", token=token, body=pol, key=key)

    def policies(self, rid):
        return self.call("GET", f"/restaurants/{quote(rid, safe='')}/policies")

    def series(self, token, body=_NO, key=_AUTO, raw=None):
        if key is _AUTO:
            key = new_key()
        return self.call("POST", "/series", token=token, body=body, key=key, raw=raw)

    def get_series(self, token, sid):
        return self.call("GET", f"/series/{quote(sid, safe='')}", token=token)

    # --- public (spec §8) --------------------------------------------------------------
    def avail(self, rid=_NO, date=_NO, party=_NO, extra=None):
        params = {}
        if rid is not _NO:
            params["restaurant_id"] = rid
        if date is not _NO:
            params["date"] = date
        if party is not _NO:
            params["party_size"] = str(party)
        if extra:
            params.update(extra)
        return self.call("GET", "/availability", params=params)

    def slots(self, rid, date, party):
        r = self.avail(rid, date, party)
        expect(r, 200)
        return r.json["slots"]

    def free_tables(self, rid, local, party=1):
        """available_table_ids of the slot starting at `local` (None if no such slot)."""
        for s in self.slots(rid, local[:10], party):
            if s["starts_at_local"] == local:
                return s["available_table_ids"]
        return None


# --- assertions ---------------------------------------------------------------------------

def assert_error_body(r):
    """Spec §5: every 4xx/5xx carries {"error": {"code": ..., "message": ...}}."""
    assert isinstance(r.json, dict), f"error response without a JSON object body: {r!r}"
    err = r.json.get("error")
    assert isinstance(err, dict), f"error body lacks an 'error' object: {r!r}"
    assert isinstance(err.get("code"), str) and err["code"], f"error.code missing: {r!r}"
    assert isinstance(err.get("message"), str), f"error.message missing: {r!r}"


def expect(r, status, code=None):
    want = f"{status} {code}" if code else f"{status}"
    if status >= 400 and code is not None and r.status == status:
        assert_error_body(r)
        assert r.json["error"]["code"] == code, f"expected {want}, got {r!r}"
    assert r.status == status, f"expected {want}, got {r!r}"
    if status >= 400:
        assert_error_body(r)
    return r.json


def expect_no_5xx(r):
    assert r.status < 500, f"5xx response (spec §5 forbids): {r!r}"
    if r.status >= 400:
        assert_error_body(r)


RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
REF_RE = re.compile(r"^[A-Z0-9]{6,12}$")
LOCAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
# stage 2: table_id is present only for single-table sets (checked in assert_res), so it is not required here
RES_KEYS = {"reservation_id", "reference", "restaurant_id", "party_size", "status",
            "starts_at_local", "starts_at", "ends_at", "created_at"}


TERMS_KEYS = {"policy_version", "slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes",
              "opening_hours", "capacities"}


def parse_ts(s):
    assert isinstance(s, str) and RFC3339.match(s), f"not an RFC 3339 timestamp with explicit offset: {s!r}"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def local_dt(local, tz):
    """Wall-clock local time resolved in tz; fold=0 = first occurrence (spec §9)."""
    return datetime.strptime(local, "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo(tz), fold=0)


def exp_start(local, tz):
    return local_dt(local, tz).isoformat()


def exp_end(local, tz, minutes):
    end = local_dt(local, tz).astimezone(timezone.utc) + timedelta(minutes=minutes)
    return end.astimezone(ZoneInfo(tz)).isoformat()


def instant(local, tz):
    return local_dt(local, tz).astimezone(timezone.utc)


def assert_ts(actual, expected):
    """Same instant AND same UTC offset (spec §3.4, §9)."""
    a = parse_ts(actual)
    e = datetime.fromisoformat(expected)
    assert a.astimezone(timezone.utc) == e.astimezone(timezone.utc) and a.utcoffset() == e.utcoffset(), \
        f"timestamp {actual!r} != expected {expected!r} (instant and offset must match)"


def assert_res(res, rest=None, table=None, local=None, party=None, status=None):
    assert isinstance(res, dict), res
    missing = RES_KEYS - set(res)
    assert not missing, f"reservation lacks {sorted(missing)}: {res}"
    assert isinstance(res["reference"], str) and REF_RE.match(res["reference"]), \
        f"reference must be 6-12 chars of A-Z0-9 (spec §8): {res['reference']!r}"
    assert isinstance(res["reservation_id"], str) and 1 <= len(res["reservation_id"]) <= 64, res
    for k in ("starts_at", "ends_at", "created_at"):
        parse_ts(res[k])
    assert isinstance(res["starts_at_local"], str) and LOCAL_RE.match(res["starts_at_local"]), res
    # stage 2: table_ids always; table_id exactly when the set has one member (S2-035)
    assert isinstance(res.get("table_ids"), list) and 1 <= len(res["table_ids"]) <= 2,         f"reservation lacks table_ids (stage-2 'Responses always carry table_ids'): {res}"
    if len(res["table_ids"]) == 1:
        assert res.get("table_id") == res["table_ids"][0], f"single-table reservation must carry table_id: {res}"
    else:
        assert "table_id" not in res, f"multi-table reservation must omit table_id: {res}"
    # stage 3: every reservation response carries revision and accepted_terms (S3-023)
    assert type(res.get("revision")) is int and res["revision"] >= 1, f"reservation lacks a revision: {res}"
    terms = res.get("accepted_terms")
    assert isinstance(terms, dict) and TERMS_KEYS <= set(terms), f"reservation lacks complete accepted_terms: {res}"
    assert "effective_from" not in terms, f"accepted_terms must exclude effective_from: {terms}"
    if rest is not None:
        assert res["restaurant_id"] == rest["id"], res
    if table is not None:
        if isinstance(table, (list, tuple)):
            assert res["table_ids"] == list(table), res
        else:
            assert res["table_id"] == table and res["table_ids"] == [table], res
    if party is not None:
        assert res["party_size"] == party and type(res["party_size"]) is int, res
    if status is not None:
        assert res["status"] == status, res
    if local is not None:
        assert res["starts_at_local"] == local, res
        if rest is not None:
            assert_ts(res["starts_at"], exp_start(local, rest["timezone"]))
            assert_ts(res["ends_at"], exp_end(local, rest["timezone"], rest["reservation_duration_minutes"]))
    return res


def same_identity(a, b):
    for k in ("reservation_id", "reference", "created_at", "restaurant_id"):
        assert a[k] == b[k], f"{k} changed: {a[k]!r} -> {b[k]!r}"


def intervals_overlap(a, b):
    """Half-open [starts_at, ends_at) overlap on absolute instants (spec §1)."""
    a0, a1 = parse_ts(a["starts_at"]), parse_ts(a["ends_at"])
    b0, b1 = parse_ts(b["starts_at"]), parse_ts(b["ends_at"])
    return a0 < b1 and b0 < a1


def tables_of(res):
    return list(res["table_ids"]) if "table_ids" in res else [res["table_id"]]


def assert_no_overlaps(reservations):
    """No table belongs to two overlapping confirmed bookings (stage-1 §1, stage-2 combined tables)."""
    conf = [r for r in reservations if r["status"] == "confirmed"]
    for i, a in enumerate(conf):
        for b in conf[i + 1:]:
            if a["restaurant_id"] == b["restaurant_id"] and set(tables_of(a)) & set(tables_of(b)):
                assert not intervals_overlap(a, b), f"two confirmed bookings overlap on a table: {a} / {b}"


# --- parallel execution ---------------------------------------------------------------

def parallel(calls, warm=True):
    """Run callables at the same instant. Each gets its own Api (own TCP connection),
    warmed with GET /health before a barrier releases all of them together.
    Returns a list of R, or of the exception a call raised (e.g. a timeout)."""
    n = len(calls)
    barrier = threading.Barrier(n)
    out = [None] * n

    def worker(i):
        api = Api()
        try:
            if warm:
                api.call("GET", "/health")
            barrier.wait(timeout=60)
            out[i] = calls[i](api)
        except Exception as e:  # noqa: BLE001 - recorded and asserted by the caller
            out[i] = e
        finally:
            api.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    return out


def assert_all_responses(results):
    for r in results:
        assert isinstance(r, R), f"request failed without an HTTP response (timeout > 5 s?): {r!r}"
        expect_no_5xx(r)
        assert r.elapsed <= REQ_TIMEOUT, f"request exceeded 5 s: {r!r} took {r.elapsed:.2f}s"


# --- fixtures (spec §4 shape) ---------------------------------------------------------

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

THU = "2027-06-17"   # Thursday, Berlin CEST (+02:00), New York EDT (-04:00)
FRI = "2027-06-18"   # Friday
SAT = "2027-06-19"
SUN = "2027-06-20"
MON = "2027-06-14"   # Monday: r_anker closed
THU2 = "2027-06-24"  # the next Thursday
WINTER_THU = "2027-01-14"  # Thursday, Berlin CET (+01:00), New York EST (-05:00)
PAST_THU = "2025-06-19"    # Thursday in the past

ADA = {"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}
BOB = {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"}
CY = {"id": "u_cy", "email": "cy@example.com", "password": "tr0ub4dor&3x", "display_name": "Cy"}

ANKER = {
    "id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
    "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
    "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"},
                      {"weekday": "fri", "opens": "18:00", "closes": "23:30"}],
    "tables": [{"id": "t_1", "label": "1", "capacity": 2},
               {"id": "t_2", "label": "2", "capacity": 4},
               {"id": "t_3", "label": "3", "capacity": 6}],
}
HARBOR = {
    "id": "r_harbor", "name": "Harbor House", "timezone": "America/New_York",
    "slot_minutes": 15, "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 60,
    "opening_hours": [{"weekday": d, "opens": "11:10", "closes": "22:00"} for d in ALL_DAYS],
    "tables": [{"id": "h_1", "label": "A", "capacity": 2},
               {"id": "h_2", "label": "B", "capacity": 8}],
}
BIG = {
    "id": "r_big", "name": "Big Hall", "timezone": "Europe/Berlin",
    "slot_minutes": 30, "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 60,
    "opening_hours": [{"weekday": d, "opens": "10:00", "closes": "22:00"} for d in ALL_DAYS],
    "tables": [{"id": f"b_{i}", "label": f"B{i}", "capacity": 4} for i in range(1, 11)],
}
DST_BER = {
    "id": "r_dst_ber", "name": "Nachtcafe", "timezone": "Europe/Berlin",
    "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
    "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "06:00"}],
    "tables": [{"id": "d_1", "label": "1", "capacity": 4}, {"id": "d_2", "label": "2", "capacity": 4}],
}
DST_NY = {
    "id": "r_dst_ny", "name": "Night Owl", "timezone": "America/New_York",
    "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
    "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "06:00"}],
    "tables": [{"id": "n_1", "label": "1", "capacity": 4}, {"id": "n_2", "label": "2", "capacity": 4}],
}
DST_SHORT = {
    "id": "r_dst_short", "name": "Kurz", "timezone": "Europe/Berlin",
    "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
    "opening_hours": [{"weekday": "sun", "opens": "00:00", "closes": "03:30"}],
    "tables": [{"id": "s_1", "label": "1", "capacity": 4}],
}
COMBO = {
    "id": "r_combo", "name": "Gasthaus Linde", "timezone": "Europe/Berlin",
    "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
    "opening_hours": [{"weekday": d, "opens": "17:00", "closes": "23:00"} for d in ALL_DAYS],
    "tables": [{"id": "c_1", "label": "Fenster", "capacity": 2},
               {"id": "c_2", "label": "Kamin", "capacity": 4},
               {"id": "c_3", "label": "Terrasse", "capacity": 2},
               {"id": "c_4", "label": "Salon", "capacity": 6}],
    # pair order deliberately differs from fixture order for the second and third pairs
    "combinable": [["c_1", "c_2"], ["c_3", "c_2"], ["c_4", "c_1"]],
}
MGR = {"id": "u_mgr", "email": "mgr@example.com", "password": "manager pass", "display_name": "Mia"}
POL = {
    "id": "r_pol", "name": "Weinstube Pol", "timezone": "Europe/Berlin",
    "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
    "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "23:00"} for d in ALL_DAYS],
    "tables": [{"id": "p_1", "label": "Ecke", "capacity": 2},
               {"id": "p_2", "label": "Mitte", "capacity": 4},
               {"id": "p_3", "label": "Garten", "capacity": 6}],
    "combinable": [["p_1", "p_2"]],
    "manager_user_ids": ["u_mgr"],
}
POL2 = {**POL, "id": "r_pol2", "name": "Zweite Stube"}
REST = {r["id"]: r for r in (ANKER, HARBOR, BIG, DST_BER, DST_NY, DST_SHORT, COMBO, POL, POL2)}


def policy(eff, slot=60, dur=120, cut=60, hours=None, caps=None):
    return {"effective_from": eff, "slot_minutes": slot, "reservation_duration_minutes": dur,
            "cancellation_cutoff_minutes": cut,
            "opening_hours": hours if hours is not None else
            [{"weekday": d, "opens": "12:00", "closes": "22:00"} for d in ALL_DAYS],
            "capacities": caps if caps is not None else {"p_1": 3, "p_2": 4, "p_3": 8}}


def terms_of(pol, version):
    """Expected accepted_terms for a policy dict (S3-023): the policy without effective_from."""
    t = {k: copy.deepcopy(v) for k, v in pol.items() if k != "effective_from"}
    t["policy_version"] = version
    return t


def terms0(rest):
    """Policy 0 = the fixture's own rules."""
    return {"policy_version": 0, "slot_minutes": rest["slot_minutes"],
            "reservation_duration_minutes": rest["reservation_duration_minutes"],
            "cancellation_cutoff_minutes": rest["cancellation_cutoff_minutes"],
            "opening_hours": copy.deepcopy(rest["opening_hours"]),
            "capacities": {t["id"]: t["capacity"] for t in rest["tables"]}}


def assert_terms(actual, expected):
    a = dict(actual)
    for k in TERMS_KEYS:
        assert k in a, f"accepted_terms lacks {k}: {actual}"
    assert a["policy_version"] == expected["policy_version"], (actual, expected)
    for k in ("slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes", "capacities"):
        assert a[k] == expected[k], f"accepted_terms.{k}: {a[k]!r} != {expected[k]!r}"
    key = lambda h: (h["weekday"], h["opens"], h["closes"])  # noqa: E731
    assert sorted(a["opening_hours"], key=key) == sorted(expected["opening_hours"], key=key),         f"accepted_terms.opening_hours differ: {a['opening_hours']} vs {expected['opening_hours']}"


def fixture(users=(ADA, BOB, CY), restaurants=(ANKER, HARBOR, BIG, DST_BER, DST_NY, DST_SHORT),
            reservations=()):
    return copy.deepcopy({"users": list(users), "restaurants": list(restaurants),
                          "reservations": list(reservations)})


def extra_users(n, prefix="p"):
    return [{"id": f"u_{prefix}{i}", "email": f"{prefix}{i}@example.com",
             "password": f"password-{prefix}{i}", "display_name": f"P{i}"} for i in range(n)]


def body(rid, tid, local, party=2):
    return {"restaurant_id": rid, "table_id": tid, "starts_at_local": local, "party_size": party}


def seed(id_, ref, user, rid, tid, local, party=2):
    return {"id": id_, "reference": ref, "user_id": user, "restaurant_id": rid, "table_id": tid,
            "starts_at_local": local, "party_size": party}


class World:
    """A reset service plus lazily logged-in tokens for the fixture users."""

    def __init__(self, api, fx=None):
        self.api = api
        self.fx = fx if fx is not None else fixture()
        api.reset(self.fx)
        self.users = {u["id"]: u for u in self.fx["users"]}
        self._tok = {}

    def tok(self, uid):
        if uid not in self._tok:
            u = self.users[uid]
            self._tok[uid] = self.api.token(u["email"], u["password"])
        return self._tok[uid]

    @property
    def ada(self):
        return self.tok("u_ada")

    @property
    def bob(self):
        return self.tok("u_bob")

    @property
    def cy(self):
        return self.tok("u_cy")


# --- real-clock restaurant for cutoff tests --------------------------------------------

NOW_ZONES = ["Asia/Kolkata", "Asia/Tokyo", "America/Phoenix", "Pacific/Honolulu",
             "Asia/Dubai", "America/Sao_Paulo", "Asia/Shanghai"]


def now_utc():
    return datetime.now(timezone.utc)


def now_restaurant(rid="r_now", cutoff=120, slot=1, duration=30, horizon_hours=8):
    """A restaurant open every day 00:00-23:59 in a fixed-offset zone where the window
    [now - 1 h, now + horizon] lies inside one local day, so bookings near the real current
    time are on the grid and inside opening hours."""
    now = now_utc()
    for tz in NOW_ZONES:
        z = ZoneInfo(tz)
        lo, hi = (now - timedelta(hours=1)).astimezone(z), (now + timedelta(hours=horizon_hours)).astimezone(z)
        if lo.date() == hi.date() and lo.hour >= 1 and hi.hour < 23:
            break
    else:  # pragma: no cover
        raise RuntimeError("no zone fits the current time window")
    return {
        "id": rid, "name": "Right Now", "timezone": tz,
        "slot_minutes": slot, "reservation_duration_minutes": duration,
        "cancellation_cutoff_minutes": cutoff,
        "opening_hours": [{"weekday": d, "opens": "00:00", "closes": "23:59"} for d in ALL_DAYS],
        "tables": [{"id": f"{rid}_t{i}", "label": str(i), "capacity": 6} for i in range(1, 9)],
    }


def local_at(rest, at_utc, round_up_minutes=1):
    """The local YYYY-MM-DDTHH:MM in rest's zone for an instant, rounded up to the grid
    (grid origin 00:00 local; slot_minutes must divide 60)."""
    z = ZoneInfo(rest["timezone"])
    t = at_utc.astimezone(z).replace(second=0, microsecond=0) + timedelta(minutes=1)
    step = rest["slot_minutes"]
    while (t.hour * 60 + t.minute) % step:
        t += timedelta(minutes=1)
    return t.strftime("%Y-%m-%dT%H:%M")


def wait_until(t_utc):
    while True:
        d = (t_utc - now_utc()).total_seconds()
        if d <= 0:
            return
        time.sleep(min(d, 1.0))
