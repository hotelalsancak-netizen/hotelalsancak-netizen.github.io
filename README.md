# rivacheck — Riva Hotel Alsancak daily checks

Two independent daily checks against ElektraWeb:

| Check | Question it answers | Entry point |
|---|---|---|
| **Room usage** (security) | Was a room used but never sold? | `analyze.py` |
| **Payments** | Did every guest who arrived yesterday actually pay? | `paycheck.py` |

---

# 1. Payment check (`paycheck.py`)

Automates the manual routine: open the reservation grid, switch to the **Günlük
Kontrol** column layout, filter *Geliş* = yesterday, and eyeball **Genel Bakiye**
for red numbers.

### The rule
`Genel Bakiye > 0` → money still owed → **flag**. `<= 0` → fine.

Balances are summed **per currency** — the hotel bills in both TRY and EUR and
adding them would be meaningless.

Cancelled/deleted reservations with a balance get their own section rather than
being mixed into the list you chase at reception.

### Setup (one-off)
```bash
python3 -m venv .venv
./.venv/bin/pip install requests
cp .env.example .env      # then fill in ELEKTRA_USER / ELEKTRA_PASS
```
Playwright/chromium are only needed for `discover.py` (re-recording API traffic), not
for the daily check.

### Usage
```bash
./daily.sh                                  # yesterday -> reports/<date>.html
./.venv/bin/python paycheck.py --date 2026-07-14
./.venv/bin/python paycheck.py --from-json testdata/screenshot_2026-07-14.json  # offline
./.venv/bin/python paycheck.py --tolerance 1.0   # ignore rounding crumbs like 0,59
```

### Exit codes
`0` everyone paid · `1` unpaid found · `2` **the check failed** — deliberately
distinct, so a broken login can never be mistaken for a clean bill of health. An
empty grid also counts as a failure, not as "everyone paid".

### Daily cron
```
0 9 * * *  /home/work/Desktop/dev/rivacheck/daily.sh >> /home/work/Desktop/dev/rivacheck/daily.log 2>&1
```
`reports/latest.html` always points at the newest report.

### Wider sweep — `audit.py` (pre-gün-sonu)
`paycheck.py` only looks at yesterday's **arrivals**. `audit.py` covers the whole
hotel and splits by who owes and how urgent:

- **A · Walkouts** — checked out with a net balance still owed (the real leak).
- **B · In-house owing** — current guests running a guest-owed balance, any arrival
  date (catches multi-night stays `paycheck.py` never sees).
- **C · Agency receivables** — net owed by the agency, shown with age; calm section.
- **D · Overpayments** — negative net on a *concluded* stay (a mid-stay prepaid
  agency booking is normal and deliberately excluded).

The signal is the **net** GENERALBALANCE, proven right against live data: guest
balance alone flagged 78 fully-settled agency checkouts. Within a positive net,
guest-owed = urgent, agency-owed = receivable.
```bash
./.venv/bin/python audit.py                # checkouts = yesterday, in-house = now
./.venv/bin/python audit.py --days 3       # sweep last 3 days of checkouts
```
Exit: `0` clear · `1` a guest owes · `2` check failed.

### Combined night-audit — `nightaudit.py` (gün sonu öncesi)
One report, run before taking gün sonu. Five pillars as tiles up top, then detail:

- 💰 **Payments** — walkouts / in-house guest debts / agency receivables (from `audit.py`).
- 🚪 **Arrivals** — expected past their arrival time still in *Rezervasyon* (never
  checked in or no-showed).
- 🛎️ **Departures** — still *InHouse* past checkout date (overstay or status error).
- 🏷️ **Rate** — in-house real rooms sold at 0 / no price (revenue leak). Virtual
  folios (BOARD/CASH FOLIO) and future/past reservations are excluded to stay quiet.
- 🪪 **KBS** — **not automated.** The hotel has KBS configured, but per-guest
  "reported to police?" status is not in `QA_HOTEL_RESERVATION`; it needs a discovery
  pass on the guest-level object. Shown as `?`, never faked green.

```bash
./.venv/bin/python nightaudit.py            # departures=yesterday, in-house=now
./.venv/bin/python nightaudit.py --days 3 --open
```
Verdict is "gün sonu alınabilir" only when every *automated* pillar is clean; KBS is
always flagged as needing a manual look. Exit: `0` ready · `1` attention · `2` failed.

### The Elektra API (verified live)
No browser needed — Elektra has a real JSON API. Full protocol notes in the
`elektra_api.py` docstring. In short:

```
POST https://wololo.elektraweb.com/GetEndpoint     # tenant 29481 -> api.s06.elektraweb.com
POST {base}Login                                   # {"Action":"Login","Usercode","Password","Tenant"}
POST {base}Select/QA_HOTEL_RESERVATION             # rows in ResultSets[0]
```
The reservation view behind `app/grid/res-all/reservation` is
**`QA_HOTEL_RESERVATION`**; `GENERALBALANCE` is the Genel Bakiye the check turns on.
Quirks worth knowing: `Where` seeds with a literal `true`, the object name appears in
both the path and the body, `HOTELID` must be filtered explicitly, and results are
paged 100 at a time.

```bash
./.venv/bin/python elektra_api.py --echo             # protocol test, no credentials
./.venv/bin/python elektra_api.py --date 2026-07-14  # raw rows
```

`elektra.py` (Playwright) and `discover.py` remain only for re-recording API traffic
if Elektra changes something. `discover.py` redacts passwords and tokens before
writing to `discover/`.

### Windows uygulaması — `gunsonu_app.py` (gece resepsiyonu için)
Resepsiyon bilgisayarında çift tıkla → **Rapor Oluştur** → rapor tarayıcıda açılır.
Bir pencere; ağ çağrısı arka planda, donmaz; hata olursa pencerede kırmızı yazı +
`hata.log`. Sonuç yeşil "gün sonu alınabilir" / kırmızı "dikkat" olarak gösterilir.

**Sadece giden bağlantı, gelen erişim yok.** Uygulama hiçbir port açmaz, sunucu
çalıştırmaz — ona *bağlanılamaz*. Yalnızca Elektra'ya (`wololo.elektraweb.com`,
`api.s06.elektraweb.com`) HTTPS ile bağlanır, sonra raporu **yerel dosya** olarak
açar. Telemetri/başka host yok.

Kurulum (Windows'ta bir kez):
```bat
copy gizli.py.example gizli.py     REM icine SALT-OKUNUR API kullanicisi + sifre yazin
build.bat                          REM -> dist\GunSonuKontrol.exe (tek dosya)
```
`dist\GunSonuKontrol.exe`'yi resepsiyon bilgisayarına kopyalayın. Python gerekmez.
Python'lu makinede exe'siz denemek için: `run.bat`.

**Gömülü şifre uyarısı:** `gizli.py` ile şifre exe'ye gömülür, ama exe açılıp
okunabilir — şifreleme değildir. Bu yüzden oraya **yönetici değil, salt-okunur bir
API kullanıcısı** yazın (Elektra: `SP_EASYPMS_CREATEAPIUSER`); ele geçse bile yalnızca
okunur, hiçbir şey değiştirilemez. `gizli.py` gitignore ile korunur, koda/gite
karışmaz. Gömülü giriş yoksa uygulama ilk açılışta bilgileri sorar ve `ayarlar.ini`'ye
kaydeder.

Bağımlılık: sadece `requests` (Playwright/tarayıcı gerekmez — API yolu ayrıştırıldı).

### 🔒 Credentials
`.env` holds a real Elektra login in plaintext and is gitignored — keep it that way.
Prefer a **dedicated read-only API user** over a personal admin account: the API
exposes `Insert`/`Update`/`Execute`, so a least-privilege user limits what this tool
could ever do. Elektra has `SP_EASYPMS_CREATEAPIUSER` for exactly this, and a
non-2FA API user is also what makes unattended cron runs possible.

---

# 2. Room-usage security check (`analyze.py`)

Cross-checks door-lock card reads against the ElektraWeb calendar to find rooms that
were **physically used but never sold**.

## The rule

For each room R and hotel night D (check-in 14:00 on D → check-out 12:00 on D+1, local):

| Calendar | Guest card opened door in window? | Verdict |
|---|---|---|
| Sold (incl. room-change replay) | — | fine, not checked |
| Vacant | no | fine, room genuinely unused |
| Vacant | yes, but reads are pre-14:00 on a next-day arrival's day | **EARLY_CHECKIN** — paid guest let in early, benign |
| Vacant | yes, otherwise | **SUSPICIOUS** — flag the room-night |

Only `Misafir Kartı` (guest card) reads count. `Master Kart` (personnel) and `İç Kol`
(inside handle) do **not** prove a sale — housekeeping legitimately enters vacant rooms.

## What makes this correct (hard-won, do not regress)

- **Replay room changes.** The calendar files a reservation under the room it ENDED in,
  so a guest moved out of a room vanishes from that room's calendar. `analyze.py`
  rebuilds each reservation's true room-by-room timeline from the Oda Değişimi report.
  It credits BOTH the change chain AND the calendar's final room (union), because some
  moves are done by editing the reservation and leave no change record (e.g. ALPARSLAN
  DİLER 96012980 → 235). Trusting either source alone manufactures false accusations.
- **RESSTATEID 2 = maintenance block, not a sale.** In a past window these are TADİLAT /
  RAMPA / SPRINKLER / SİFON etc., often zero-length. Counting them as sold would hide a
  room opened while "under maintenance" — the worst case.
- **Card IDs are recycled.** The lock "Kart kimliği" is a reused card serial (one serial
  appears in 6–9 rooms over weeks), NOT a guest identity. Never key on it. It is still
  true that a lock only opens for a card encoded for THAT room, so a Misafir read is real
  evidence a guest key for that room existed.
- **Low-battery locks triple-log.** A `Düşük voltaj` lock writes the same swipe 2–3×
  with identical card+second (room 221). De-duplicated by (card, recorded-second).
- **Coverage.** Each lock holds ~200 events; busiest reach back only ~9 days. Nights are
  complete only through the day BEFORE the read date (read 13.07 → last full night 12.07).

## Timezone

The locks record **~2h ahead of Turkish local time** (recorded 16:00 = local 14:00).
`parse_cards.py` converts every lock timestamp to local via `LOCK_OFFSET_HOURS = 2`.
ElektraWeb timestamps (room changes, reservations) are already local — no correction.

## Data sources

| File | Source | Status |
|---|---|---|
| `cardreads/<ddmmyyyy>/*.pdf` | hand terminal lock dumps, one PDF per room | ✅ have |
| `room_changes.py` → `room_changes.json` | ElektraWeb "Oda Değişimi" report (87 rows) | ✅ have |
| `occupancy.json` | ElektraWeb room calendar via API | ✅ automated |

`occupancy.json` is fetched from `FN_ROOMCALENDAR_BASIC` (see `elektra_api.py`). Its
`FROM`/`TO` select by **overlap**, so a guest staying 28.06 → 05.07 is included when
the window starts 01.07 — verified live. State 2 rows (maintenance) go in a separate
`blocks` list, not `reservations`.

## Usage — weekly run

```bash
python3 parse_cards.py cardreads/13072026 cards.json          # 1. parse room PDFs
python3 room_changes.py                                       # 2. room-change list
./.venv/bin/python elektra_api.py --occupancy 2026-07-01 2026-07-14   # 3. fetch calendar
python3 analyze.py 2026-07-06 2026-07-12                      # 4. findings.json
python3 build_report.py                                       # 5. report.html
```

Fetch occupancy a few days WIDER than the analysis window on each side so overlapping
stays and same-day moves are all present. `room_changes.py` is still hand-typed from a
one-off export; the Oda Değişimi report can be pulled the same API way when needed.

## Notes on the lock PDF format

- Each lock stores the last ~200 events, newest first.
- Columns are read by x-position; the date/time cell is **vertically centred** on its
  row (date ~5pt above the row text, time ~5pt below) — pair by nearest anchor, not by
  a forward scan.
- Days 1–9 print single-digit (`9.07.2026`).
- A **midnight** event prints an empty time. Verified fleet-wide: every such row is
  bracketed by neighbours spanning 00:00, so it is inferred as `00:00:00` and marked
  `time_inferred`.
