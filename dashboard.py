#!/usr/bin/env python3
"""
dashboard.py — Riva Hotel Alsancak Dashboard builder.

Assembles the hotel's check-lists into ONE password-protected static site that is
published on GitHub Pages. Each list is a "section"; adding a new list later is a
matter of writing one more build_* function and appending it to SECTION_ORDER.

SECURITY MODEL
  Every section is encrypted with DASH_PASSWORD (PBKDF2-SHA256 + AES-256-GCM, see
  dashcrypto.py) BEFORE it is written to disk. The published files — and therefore
  the public repo and the public URL — hold ciphertext only. The browser decrypts
  in memory after the correct password is entered (dashboard_shell.html). So guest
  data never sits in the clear anywhere outside a logged-in browser.

TWO BUILD MODES
  --build   (cloud, daily, GitHub Actions):
              fetch Elektra -> build "Gün Sonu" + "Dünün Ödemesi",
              reuse the committed encrypted "Kart Güvenliği" blob (site_data/) if
              present, then write public/  (login shell + data/*.enc.json + manifest).
  --cards   (local, weekly, on the hotel PC):
              build "Kart Güvenliği" from the door-lock exports in cardreads/ +
              occupancy.json, encrypt it, write site_data/kart.enc.json (committed).
              The next --build picks it up. Run kart-yayinla.sh to build+push+deploy.

Env: ELEKTRA_HOTELID / ELEKTRA_USER / ELEKTRA_PASS (Secrets in cloud, .env locally),
     DASH_PASSWORD (the single dashboard password, same in both places).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

import dashcrypto

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
SITE_DATA = ROOT / "site_data"          # committed encrypted blobs built locally
SHELL = ROOT / "dashboard_shell.html"

# Display order of the tiles. A key here maps to site_data/<key>.enc.json (local,
# committed) or is built live in build_cloud(). Add future lists by extending this.
SECTION_ORDER = ["gunsonu", "odeme", "kasa", "iptal", "indirim", "bakiye", "kart", "stats"]

TR_MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tr_date(d: dt.date) -> str:
    return f"{d.day} {TR_MONTHS[d.month]} {d.year}"


def now_str() -> str:
    n = dt.datetime.now()
    return f"{n.day:02d}.{n.month:02d}.{n.year} {n.hour:02d}:{n.minute:02d}"


def elektra_env() -> dict:
    return {"ELEKTRA_HOTELID": os.environ.get("ELEKTRA_HOTELID", "29481"),
            "ELEKTRA_USER": os.environ.get("ELEKTRA_USER", ""),
            "ELEKTRA_PASS": os.environ.get("ELEKTRA_PASS", "")}


# ---------------------------------------------------------------------------
# Section builders — each returns a dict {label, count, count_label, tone, sub,
# updated, html}. tone: "bad" (needs attention) or "ok".
# ---------------------------------------------------------------------------

def build_gunsonu(env) -> dict:
    import nightaudit
    res = nightaudit.generate(env=env, reports_dir=PUBLIC / "_tmp")
    html = Path(res["path"]).read_text(encoding="utf-8")
    c = res["counts"]
    n = c["needs_attention"]
    d = dt.date.fromisoformat(res["date"])
    return {"label": "Gün Sonu Hazırlık", "count": n, "count_label": "dikkat",
            "tone": "bad" if n else "ok",
            "sub": f"{tr_date(d)} kapanışı · misafir/no-show/acenta",
            "updated": now_str(), "html": html}


def build_odeme(env) -> dict:
    import paycheck
    from elektra_api import fetch_arrivals
    date = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    rows = fetch_arrivals(date, env=env)
    if not rows:
        raise RuntimeError(f"{date} için rezervasyon dönmedi — boş grid 'hepsi ödedi' sayılmaz.")
    groups = paycheck.classify(rows)
    meta = {"total": len(rows), "tolerance": paycheck.DEFAULT_TOLERANCE,
            "generated": now_str(), "note": None,
            "source": "ElektraWeb res-all/reservation", "missing": 0}
    html = paycheck.render(date, groups, meta)
    n = len(groups["unpaid"])
    return {"label": "Dünün Ödeme Kontrolü", "count": n, "count_label": "ödenmemiş",
            "tone": "bad" if n else "ok",
            "sub": f"{tr_date(dt.date.fromisoformat(date))} girişleri · {len(rows)} rezervasyon",
            "updated": now_str(), "html": html}


def build_kart() -> dict:
    """Local-only: needs cards.json (door-lock PDFs), room_changes.json, occupancy.json."""
    import build_report
    from analyze import analyze
    for f in ("cards.json", "room_changes.json", "occupancy.json"):
        if not (ROOT / f).exists():
            raise RuntimeError(f"{f} yok — kilit export'u ve occupancy çekimi gerekli.")
    cards = json.loads((ROOT / "cards.json").read_text())
    changes = json.loads((ROOT / "room_changes.json").read_text())
    occ = json.loads((ROOT / "occupancy.json").read_text())
    html = build_report.build(cards, changes, occ)
    findings = analyze(cards, occ, changes,
                       build_report.LO.isoformat(), build_report.HI.isoformat())
    n = sum(1 for f in findings if f["status"] == "SUSPICIOUS")
    span = f'{build_report.LO.strftime("%d.%m")}–{build_report.HI.strftime("%d.%m.%Y")}'
    return {"label": "Haftalık Kart Güvenliği", "count": n, "count_label": "şüpheli",
            "tone": "bad" if n else "ok",
            "sub": f"{span} · satılmadan kullanılan odalar",
            "updated": now_str(), "html": html}


# ---------------------------------------------------------------------------
# Encrypt + write
# ---------------------------------------------------------------------------

def password() -> str:
    pw = os.environ.get("DASH_PASSWORD", "").strip()
    if not pw:
        print("DASH_PASSWORD yok (Secret / .env).", file=sys.stderr)
        sys.exit(2)
    return pw


def encrypt_section(section: dict, pw: str) -> dict:
    keep = ("label", "count", "count_label", "tone", "sub", "updated", "html")
    payload = json.dumps({k: section.get(k) for k in keep}, ensure_ascii=False)
    return dashcrypto.encrypt(payload, pw)


def write_blob(key: str, blob: dict, out_dir: Path):
    d = out_dir / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.enc.json").write_text(json.dumps(blob), encoding="utf-8")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def build_cards():
    """Local weekly: build the card-security section and commit its encrypted blob."""
    pw = password()
    section = build_kart()
    blob = encrypt_section(section, pw)
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "kart.enc.json").write_text(json.dumps(blob), encoding="utf-8")
    print(f"KART bölümü şifrelendi -> site_data/kart.enc.json "
          f"(şüpheli={section['count']}, {section['sub']})")
    print("Yayınlamak için: ./kart-yayinla.sh  (commit + push + workflow tetikler)")


def build_cloud():
    """Cloud daily: build live sections, reuse committed card blob, write public/."""
    pw = password()
    env = elektra_env()
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)

    import checks

    built = []

    # Live sections (Elektra API only). A broken section is logged and skipped so
    # one bad fetch never blanks the whole dashboard.
    live = (("gunsonu", build_gunsonu), ("odeme", build_odeme),
            ("kasa", checks.build_kasa), ("iptal", checks.build_iptal),
            ("indirim", checks.build_indirim), ("bakiye", checks.build_bakiye),
            ("stats", checks.build_stats))
    for key, fn in live:
        try:
            section = fn(env)
            write_blob(key, encrypt_section(section, pw), PUBLIC)
            built.append(key)
            print(f"  {key}: {section['count']} {section.get('count_label','')} ✓")
        except Exception as e:
            print(f"  {key}: ÜRETİLEMEDİ — {e}", file=sys.stderr)

    # Card section: reuse the committed encrypted blob (built locally, weekly).
    committed = SITE_DATA / "kart.enc.json"
    if committed.exists():
        (PUBLIC / "data").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(committed, PUBLIC / "data" / "kart.enc.json")
        built.append("kart")
        print("  kart: commit edilmiş şifreli blob kopyalandı ✓")
    else:
        print("  kart: site_data/kart.enc.json yok — kart tile'ı atlandı "
              "(yerelde ./kart-yayinla.sh çalıştırın)")

    if not any(k in built for k in ("gunsonu", "odeme")):
        print("HİÇBİR CANLI BÖLÜM ÜRETİLEMEDİ — yayın iptal.", file=sys.stderr)
        sys.exit(2)

    # Login shell + manifest (ordered by SECTION_ORDER, only what we actually built).
    order = [k for k in SECTION_ORDER if k in built]
    shutil.copyfile(SHELL, PUBLIC / "index.html")
    (PUBLIC / "data" / "manifest.json").write_text(
        json.dumps({"built": now_str(), "sections": order}, ensure_ascii=False),
        encoding="utf-8")
    (PUBLIC / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (PUBLIC / ".nojekyll").write_text("", encoding="utf-8")

    # Clean the temp report dir nightaudit wrote into.
    tmp = PUBLIC / "_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)

    print(f"YAYINA HAZIR -> public/  | bölümler: {', '.join(order)}")


def main():
    ap = argparse.ArgumentParser(description="Riva Hotel Alsancak Dashboard builder")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true", help="bulut: canlı bölümleri üret + public/ yaz")
    g.add_argument("--cards", action="store_true", help="yerel: kart güvenlik bölümünü üret + şifrele")
    a = ap.parse_args()
    if a.cards:
        build_cards()
    else:
        build_cloud()
    return 0


if __name__ == "__main__":
    sys.exit(main())
