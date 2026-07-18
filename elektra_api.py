#!/usr/bin/env python3
"""
elektra_api.py — ElektraWeb JSON API client. Primary data source for paycheck.py.

Elektra has a real API, so we don't need a browser at all. `elektra.py` (Playwright)
stays as a fallback / discovery aid; this module is what the daily check should use.

Everything below was reverse engineered from the public frontend bundle
(app.elektraweb.com/main.*.js) and verified live as far as is possible without
credentials.

PROTOCOL (verified)
    Every call is  POST {base}{Action}  with a JSON body whose "Action" repeats the
    path. Auth is a LoginToken carried on subsequent calls.

    1. Resolve the tenant's API host — unauthenticated, confirmed working:
         POST https://wololo.elektraweb.com/GetEndpoint
         {"Action":"GetEndpoint","Fields":["TENANTUID","API_URL","USE_IDP"],
          "Tenant":"29481"}
         -> {"API_URL":"https://api.s06.elektraweb.com/",
             "TENANTUID":"6FF96EDC-1DCD-464E-95EA-C0E4354F8855","USE_IDP":false}
         Riva lives on server s06 and does NOT use SSO, so usercode/password works.

    2. Login:
         POST {base}Login  {"Action":"Login","Usercode":…,"Password":…,"Tenant":"29481"}
         -> {"Success":true,"LoginToken":…,"AdminLevel":…,"RoleName":…}
         Response Code 20/30/31 = two-factor challenge (needs AuthCode).
         ttCaptchaId / ttCaptchaCode exist for captcha challenges.

    3. Query — a generic SQL-ish interface over tables/views. Captured from the real
       client, so this is the exact shape the server expects:
         POST {base}Select/QA_HOTEL_RESERVATION
         {"Action":"Select","Object":"QA_HOTEL_RESERVATION","Select":[cols],
          "Where":[true,{"Column":"HOTELID","Operator":"=","Value":29481}],
          "OrderBy":[{"Column":"CHECKIN","Direction":"DESC"}],
          "Paging":{"ItemsPerPage":100,"Current":1},"TotalCount":false,"Joins":[]}
       -> {"ResultSets":[[ {row}, … ]], "DataTypes":…, "TotalCount":…}
       Rows live in ResultSets[0]. Note the literal `true` seeding Where, and that
       the object name appears BOTH in the path and in the body.

    Confirmed live WITHOUT credentials:
      * POST /Echo   {"Action":"Echo","Data":"rivacheck"} -> {"Data":"rivacheck"} 200
      * POST /Select without a token -> 403 "You do not have permission to Select
        on {{HOTEL}}."  — the API is live and enforcing permissions.

    Other actions seen in the bundle / live traffic: Insert, Update, Execute,
    Function, GetConfig, Logout, LockScreen, RemoteLogin, SSO, HtmlToPdf, GetLog.
    Config for a screen: POST {base}GetConfig/grid.res-all.config

RESERVATION VIEW — QA_HOTEL_RESERVATION (verified). Its columns match the "Günlük
Kontrol" layout: ROOMNO, ROOMSTATE, AGENCY, GUESTNAMES, CHECKIN, CHECKOUT, ADULT,
GUESTBALANCE, AGENCYBALANCE, GENERALBALANCE, AVERAGENIGHTPRICE, CURRENCYRATE,
CURRENCYCODE, RESSTATE, RESID.
GENERALBALANCE is the "Genel Bakiye" the whole check turns on.
"""
import argparse, datetime as dt, json, os, pathlib, sys

import requests

GET_ENDPOINT_URL = "https://wololo.elektraweb.com/GetEndpoint"
DEFAULT_TENANT = "29481"          # Riva Hotel Alsancak
TIMEOUT = 60

# Grid column -> our field name. Column names verified from the frontend bundle.
FIELD_MAP = {
    "ROOMNO": "room",
    "AGENCY": "agency",
    "GUESTNAMES": "guest",
    "CHECKIN": "checkin",
    "CHECKOUT": "checkout",
    "GUESTBALANCE": "misafir_bakiye",
    "AGENCYBALANCE": "acenta_bakiye",
    "GENERALBALANCE": "genel_bakiye",
    "AVERAGENIGHTPRICE": "ort_oda",
    "TOTALPRICE": "toplam",
    "PAYMENTTYPE": "odeme_tipi",
    "CURRENCYCODE": "currency",
    "RESSTATE": "durum",
    "RESID": "rez_id",
    "ROOMSTATE": "oda_durum",
    "ADULT": "yetiskin",
}
SELECT_COLUMNS = list(FIELD_MAP.keys())

# VERIFIED: this is the view behind app/grid/res-all/reservation. Captured from the
# real client, which posts to Select/QA_HOTEL_RESERVATION. Guessing was hopeless —
# the API returns an identical 403 for "no permission" and "no such object".
RES_OBJECT = "QA_HOTEL_RESERVATION"

class ElektraError(RuntimeError):
    """Anything that stopped us getting the data. Never means 'everyone paid'."""


def load_env(path=".env"):
    """Read KEY=VALUE lines from `path`. Kept dependency-free (no python-dotenv) so
    the Windows build needs nothing but `requests`. Lives here rather than in
    elektra.py so the whole API path stays clear of Playwright."""
    if not os.path.exists(path):
        raise ElektraError(f"{path} missing — copy .env.example to .env and fill it in.")
    env = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in ("ELEKTRA_USER", "ELEKTRA_PASS"):
        if not env.get(k):
            raise ElektraError(f"{k} not set in {path}")
    return env


class Elektra:
    def __init__(self, tenant=DEFAULT_TENANT):
        self.tenant = tenant
        self.base = None
        self.token = None
        self.s = requests.Session()

    def _post(self, path, body, auth=True, action_name=None):
        """POST {base}{path}. The body's Action is the bare action name, while the
        path may carry the object too (e.g. path='Select/QA_HOTEL_RESERVATION',
        Action='Select') — that is what the real client does."""
        if not self.base:
            raise ElektraError("call resolve_endpoint() first")
        payload = {"Action": action_name or path, **body}
        headers = {"Content-Type": "application/json"}
        if auth and self.token:
            payload["LoginToken"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            r = self.s.post(self.base + path, json=payload, headers=headers,
                            timeout=TIMEOUT)
        except requests.RequestException as e:
            raise ElektraError(f"{path} request failed: {e}") from e
        if r.status_code == 403:
            raise ElektraError(f"{path} denied (403): {r.text[:200]}")
        if not r.ok:
            raise ElektraError(f"{path} HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise ElektraError(f"{path} returned non-JSON: {r.text[:200]}")

    def resolve_endpoint(self):
        try:
            r = requests.post(GET_ENDPOINT_URL, json={
                "Action": "GetEndpoint",
                "Fields": ["TENANTUID", "API_URL", "USE_IDP"],
                "Tenant": self.tenant}, timeout=TIMEOUT)
            r.raise_for_status()
            d = r.json()
        except requests.RequestException as e:
            raise ElektraError(f"GetEndpoint failed: {e}") from e
        self.base = d.get("API_URL") or d.get("Endpoint")
        if not self.base:
            raise ElektraError(f"no API_URL for tenant {self.tenant}: {d}")
        if not self.base.endswith("/"):
            self.base += "/"
        if d.get("USE_IDP"):
            raise ElektraError("tenant uses SSO; usercode/password login won't work.")
        return self.base

    def echo(self, data="ping"):
        return self._post("Echo", {"Data": data}, auth=False)

    def login(self, usercode, password, auth_code=None):
        body = {"Usercode": usercode, "Password": password, "Tenant": self.tenant}
        if auth_code:
            body["AuthCode"] = auth_code
        d = self._post("Login", body, auth=False)
        code = d.get("Code")
        if code is not None and str(code).isdigit() and int(code) in (20, 30, 31):
            raise ElektraError(
                f"login needs two-factor auth (Code {code}). Pass --auth-code, or "
                "create a dedicated API user without 2FA for unattended cron runs.")
        if not d.get("LoginToken"):
            raise ElektraError(f"login rejected: {json.dumps(d, ensure_ascii=False)[:300]}")
        self.token = d["LoginToken"]
        return d

    def select(self, obj, columns=None, where=None, order_by=None, per_page=100,
               max_pages=200):
        """Select rows, following pagination. Verified against the live API.

        Request shape copied from what the res-all grid actually sends:
          POST {base}Select/{Object}
          {"Action":"Select","Object":…,"Select":[…],
           "Where":[true, {"Column":…,"Operator":…,"Value":…}],
           "OrderBy":[…],"Paging":{"ItemsPerPage":100,"Current":1},
           "TotalCount":false,"Joins":[]}

        The leading `true` in Where is not a typo — the server builds "WHERE true AND
        …", so the list seeds with a literal true and every real condition ANDs onto
        it. Omitting it returns an error.
        """
        rows, page = [], 1
        while True:
            body = {
                "Object": obj,
                "Select": columns or [],
                "Where": [True] + list(where or []),
                "OrderBy": order_by or [],
                "Paging": {"ItemsPerPage": per_page, "Current": page},
                "TotalCount": False,
                "Joins": [],
            }
            d = self._post(f"Select/{obj}", body, action_name="Select")
            sets = d.get("ResultSets") if isinstance(d, dict) else None
            if not isinstance(sets, list) or not sets:
                raise ElektraError("unexpected Select response shape: "
                                   f"{json.dumps(d, ensure_ascii=False)[:300]}")
            batch = sets[0] or []
            rows.extend(batch)
            if len(batch) < per_page or page >= max_pages:
                return rows
            page += 1

    def function(self, name, parameters, per_page=50000):
        """Call a server FUNCTION (as opposed to a Select over a view).

        Captured from the room-calendar screen:
          POST {base}Function/FN_ROOMCALENDAR_BASIC
          {"Action":"Function","Object":"FN_ROOMCALENDAR_BASIC",
           "Parameters":{…},"Paging":{"Current":1,"ItemsPerPage":50000},
           "LoginToken":…}
        The result is a list of result-sets; the rows are in the first one.
        """
        d = self._post(f"Function/{name}",
                       {"Object": name, "Parameters": parameters,
                        "Paging": {"Current": 1, "ItemsPerPage": per_page}},
                       action_name="Function")
        if isinstance(d, list) and d and isinstance(d[0], list):
            return d[0]
        if isinstance(d, dict):
            sets = d.get("ResultSets")
            if isinstance(sets, list) and sets:
                return sets[0] or []
        raise ElektraError(f"unexpected Function/{name} response shape: "
                           f"{json.dumps(d, ensure_ascii=False)[:200]}")


def normalise(rec):
    return {FIELD_MAP[k.upper()]: v for k, v in rec.items() if k.upper() in FIELD_MAP}


def connect(env=None):
    env = env or load_env()
    e = Elektra(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))
    e.resolve_endpoint()
    e.login(env["ELEKTRA_USER"], env["ELEKTRA_PASS"], env.get("ELEKTRA_AUTHCODE"))
    return e, env


def fetch_arrivals(date, env=None, raw=False):
    """Reservations whose arrival (CHECKIN) falls on `date` (YYYY-MM-DD).

    Mirrors the res-all grid filtered to Geliş = date. HOTELID is not optional —
    the view spans hotels, so without it you would be checking someone else's.
    """
    e, env = connect(env)
    obj = env.get("ELEKTRA_RES_OBJECT", RES_OBJECT)
    hotel_id = int(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))
    rows = e.select(obj, SELECT_COLUMNS, where=[
        {"Column": "HOTELID", "Operator": "=", "Value": hotel_id},
        {"Column": "CHECKIN", "Operator": ">=", "Value": f"{date} 00:00:00"},
        {"Column": "CHECKIN", "Operator": "<=", "Value": f"{date} 23:59:59.999"},
    ], order_by=[{"Column": "CHECKIN", "Direction": "ASC"}])
    return rows if raw else [normalise(r) for r in rows]


def _connected_select(where, order_by=None, env=None, raw=False):
    e, env = connect(env)
    obj = env.get("ELEKTRA_RES_OBJECT", RES_OBJECT)
    hotel_id = int(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))
    rows = e.select(obj, SELECT_COLUMNS,
                    where=[{"Column": "HOTELID", "Operator": "=", "Value": hotel_id}] + where,
                    order_by=order_by)
    return rows if raw else [normalise(r) for r in rows]


def fetch_checkouts(date, env=None, raw=False):
    """Reservations whose departure (CHECKOUT) falls on `date`. The walkout check:
    a guest who left with a net balance owed."""
    return _connected_select(
        [{"Column": "CHECKOUT", "Operator": ">=", "Value": f"{date} 00:00:00"},
         {"Column": "CHECKOUT", "Operator": "<=", "Value": f"{date} 23:59:59.999"}],
        order_by=[{"Column": "CHECKOUT", "Direction": "ASC"}], env=env, raw=raw)


def fetch_inhouse(env=None, raw=False):
    """All guests currently in house, regardless of arrival date — so a multi-night
    stay building an unpaid balance is caught, not just yesterday's arrivals."""
    return _connected_select(
        [{"Column": "RESSTATE", "Operator": "=", "Value": "InHouse"}],
        order_by=[{"Column": "CHECKOUT", "Direction": "ASC"}], env=env, raw=raw)


def fetch_departed_range(frm, to, env=None, raw=False):
    """Checkouts across a date range [frm, to] — for sweeping several days of
    departures at once (e.g. catching a walkout missed over a weekend)."""
    return _connected_select(
        [{"Column": "CHECKOUT", "Operator": ">=", "Value": f"{frm} 00:00:00"},
         {"Column": "CHECKOUT", "Operator": "<=", "Value": f"{to} 23:59:59.999"},
         {"Column": "RESSTATE", "Operator": "=", "Value": "CheckOut"}],
        order_by=[{"Column": "CHECKOUT", "Direction": "ASC"}], env=env, raw=raw)


# ---------------------------------------------------------------------------
# Extended fetchers for the owner-control lists (cash/POS reconciliation,
# cancels, discounts, balances, stats). These return RAW rows (original column
# names) so the check modules can read the full reservation / folio model.
# ---------------------------------------------------------------------------

RES_EXT_COLUMNS = [
    "RESID", "ROOMNO", "GUESTNAMES", "AGENCY", "CHECKIN", "CHECKOUT",
    "RESSTATE", "RESSTATEID", "GENERALBALANCE", "GUESTBALANCE", "AGENCYBALANCE",
    "TOTALPRICE", "AVERAGENIGHTPRICE", "PAIDAMOUNT", "NIGHT", "ADULT",
    "ROOMTYPE", "SOURCE", "RATECODE", "PAYMENTTYPENAME", "CURRENCYCODE",
    "CANCEL_DATE", "CANCELUSER", "CREATORUSER", "UPDATEUSER", "CREATEDATE",
]


def fetch_reservations(where, env=None, columns=None, order_by=None):
    """Raw reservation rows for an arbitrary WHERE (HOTELID is prepended). Original
    column names are kept untouched — the control lists want the full model."""
    e, env = connect(env)
    hid = int(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))
    return e.select(env.get("ELEKTRA_RES_OBJECT", RES_OBJECT), columns or RES_EXT_COLUMNS,
                    where=[{"Column": "HOTELID", "Operator": "=", "Value": hid}] + list(where),
                    order_by=order_by, per_page=500)


def fetch_reservations_between(col, frm, to, env=None, extra=None, columns=None):
    """Reservations whose `col` (CHECKIN / CHECKOUT / CANCEL_DATE …) is in [frm, to]."""
    w = [{"Column": col, "Operator": ">=", "Value": f"{frm} 00:00:00"},
         {"Column": col, "Operator": "<=", "Value": f"{to} 23:59:59.999"}]
    return fetch_reservations(w + list(extra or []), env=env, columns=columns,
                              order_by=[{"Column": col, "Direction": "ASC"}])


FOLIO_OBJECT = "QA_HOTEL_FOLIO"
FOLIO_COLUMNS = [
    "ID", "RESID", "ROOMNO", "GUESTNAMES", "AGENCY", "DEPNAME", "DEPCODE",
    "DEPTTYPE", "DEPTTYPENAME", "TYPE", "REVENUENAME", "TOTAL", "CTOTAL",
    "CURRENCY", "USERCODE", "USERFULLNAME", "FOLIODATE",
]


def fetch_folio(frm, to, env=None, columns=None):
    """Folio lines (charges + collections) with FOLIODATE in [frm, to] — raw rows.

    DEPTTYPENAME 'PAYMENT' rows are collections; DEPNAME is the method
    (Cash / Credit Card / Havale / CityLedger). 'REVENUE' rows are charges.
    TYPE in ('Discount','Rebate') are price reductions. USERFULLNAME is who did it."""
    e, env = connect(env)
    hid = int(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))
    return e.select(FOLIO_OBJECT, columns or FOLIO_COLUMNS,
                    where=[{"Column": "HOTELID", "Operator": "=", "Value": hid},
                           {"Column": "FOLIODATE", "Operator": ">=", "Value": f"{frm} 00:00:00"},
                           {"Column": "FOLIODATE", "Operator": "<=", "Value": f"{to} 23:59:59.999"}],
                    per_page=1000)


# ---------------------------------------------------------------------------
# Room calendar — the occupancy source for the room-usage security check.
# ---------------------------------------------------------------------------
# FN_ROOMCALENDAR_BASIC is what draws the Oda Planı. Verified live 15.07.2026.
#
# FROM/TO select by OVERLAP, not by start date: asking FROM=2026-07-15 returned
# stays that checked in as far back as 2026-06-15 and were still running. That is
# exactly what the check needs — a guest staying 28.06 -> 05.07 must not be missed,
# or their room reads as unsold and innocent nights get flagged.
#
# RESSTATEID, verified against live data for 01–14.07.2026:
#   3  Konaklayan    guest in house      -> SOLD
#   4  Çıkış yapmış  guest checked out   -> SOLD
#   2  Rezervasyon/blocked. In a PAST window every one of these was an out-of-order
#      block, not a guest: GUESTNAMES reads TADİLAT / RAMPA / SPRINKLER / SİFON /
#      KAPI ARIZASI / KAPALI, AGENCY empty, and many are zero-length (checkin ==
#      checkout) or even reversed (05.07 -> 04.07). NOT a sale — counting these as
#      sold would hide the very thing we are looking for: a room marked under
#      maintenance but opened with a guest card.
ROOMCAL_FUNCTION = "FN_ROOMCALENDAR_BASIC"
SOLD_STATES = {3, 4}
BLOCK_STATE = 2
STATE_NAMES = {2: "Rezervasyon / blocked", 3: "Konaklayan", 4: "Çıkış yapmış"}


def fetch_room_calendar(frm, to, env=None, raw=False):
    """Calendar rows overlapping [frm, to] (YYYY-MM-DD)."""
    e, env = connect(env)
    rows = e.function(ROOMCAL_FUNCTION, {
        "FROM": frm, "TO": to, "ROOMTYPEIDS": None,
        "HOTELID": int(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))})
    return rows if raw else to_occupancy(rows, frm, to)


def to_occupancy(rows, frm, to):
    """Split raw calendar rows into real guest occupancy vs maintenance blocks."""
    res, blocks = [], []
    for r in rows:
        rec = dict(room=str(r["ROOMNO"]),
                   guest=(r.get("GUESTNAMES") or "").strip(),
                   checkin=str(r["CHECKIN"])[:10],
                   checkout=str(r["CHECKOUT"])[:10],
                   rez_id=str(r.get("RESID") or r.get("ID") or ""),
                   state=r["RESSTATEID"],
                   state_name=STATE_NAMES.get(r["RESSTATEID"], str(r["RESSTATEID"])),
                   agency=(r.get("AGENCY") or "").strip())
        if r["RESSTATEID"] in SOLD_STATES:
            res.append(rec)
        elif r["RESSTATEID"] == BLOCK_STATE:
            blocks.append(rec)
    return {"fetched": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "from": frm, "to": to, "reservations": res, "blocks": blocks}


def probe(env=None):
    """Sanity-check the connection and the reservation view."""
    e, env = connect(env)
    print(f"[*] logged in to {e.base} as {env['ELEKTRA_USER']}")
    rows = e.select(RES_OBJECT, SELECT_COLUMNS,
                    where=[{"Column": "HOTELID", "Operator": "=",
                            "Value": int(env.get("ELEKTRA_HOTELID", DEFAULT_TENANT))}],
                    per_page=5, max_pages=1)
    print(f"[*] {RES_OBJECT} readable — sample keys: {list(rows[0].keys())[:8] if rows else '—'}")
    return [RES_OBJECT]


def main():
    ap = argparse.ArgumentParser(description="ElektraWeb JSON API client")
    ap.add_argument("--date", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--probe", action="store_true", help="find the reservation view")
    ap.add_argument("--echo", action="store_true", help="protocol test, no credentials")
    ap.add_argument("--dump", help="write raw rows to this file")
    ap.add_argument("--occupancy", nargs=2, metavar=("FROM", "TO"),
                    help="fetch the room calendar for FROM..TO -> occupancy.json")
    a = ap.parse_args()

    if a.occupancy:
        frm, to = a.occupancy
        occ = fetch_room_calendar(frm, to)
        if not occ["reservations"]:
            raise ElektraError(
                f"no guest reservations returned for {frm}..{to}. Refusing to write an "
                "empty occupancy file — it would mark every room unsold and flag the "
                "whole hotel.")
        pathlib.Path("occupancy.json").write_text(
            json.dumps(occ, ensure_ascii=False, indent=1))
        print(f"{len(occ['reservations'])} guest reservations (sold), "
              f"{len(occ['blocks'])} maintenance/blocked rows -> occupancy.json")
        return 0

    if a.echo:
        e = Elektra()
        print("endpoint:", e.resolve_endpoint())
        print("echo:   ", e.echo("rivacheck"))
        return 0
    if a.probe:
        return 0 if probe() else 2

    rows = fetch_arrivals(a.date)
    if a.dump:
        pathlib.Path(a.dump).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"{len(rows)} rows for {a.date}")
    print(json.dumps(rows[:3], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ElektraError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
