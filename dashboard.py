#!/usr/bin/env python3
"""
dashboard.py — Riva Hotel Alsancak Dashboard builder.

Assembles the hotel's check-lists into ONE password-protected static site that is
published on GitHub Pages. Each list is a "section"; adding a new list later is a
matter of writing one more build_* function and appending it to SECTION_ORDER.

SECURITY MODEL
  Every section is encrypted per role (PBKDF2-SHA256 + AES-256-GCM, see
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
     DASH_PW_MANAGER (yönetim/sahip — her bölümü açar),
     DASH_PW_RECEPTION (resepsiyon — yalnızca RECEPTION_SECTIONS).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
from zoneinfo import ZoneInfo
from pathlib import Path

import dashcrypto
import pazarlama   # Pazarlama sayfaları: api.rivaalsancak.com (24.11.2026)

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
SITE_DATA = ROOT / "site_data"          # committed encrypted blobs built locally
SHELL = ROOT / "dashboard_shell.html"

# Display order of the tiles. A key here maps to site_data/<key>.enc.json (local,
# committed) or is built live in build_cloud(). Add future lists by extending this.
SECTION_ORDER = ["anlik", "gunsonu", "odeme", "gunluk", "kasa", "nakit", "iptal", "indirim", "bakiye", "eksik",
                 "fiyat", "kart", "stats", "satis", "gelirgider", "borclar", "vergi", "tvkart",
                 "yorumkart", "odakontrol", "yorumlar", "paylasim", "kurumlar"]

TR_MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tr_date(d: dt.date) -> str:
    return f"{d.day} {TR_MONTHS[d.month]} {d.year}"


def now_str() -> str:
    n = dt.datetime.now(ZoneInfo("Europe/Istanbul"))   # bulut UTC'de çalışır; sahip TR saatini görsün
    return f"{n.day:02d}.{n.month:02d}.{n.year} {n.hour:02d}:{n.minute:02d}"


def elektra_env() -> dict:
    return {"ELEKTRA_HOTELID": os.environ.get("ELEKTRA_HOTELID", "29481"),
            "ELEKTRA_USER": os.environ.get("ELEKTRA_USER", ""),
            "ELEKTRA_PASS": os.environ.get("ELEKTRA_PASS", ""),
            "ELEKTRA_TOTP_SECRET": os.environ.get("ELEKTRA_TOTP_SECRET", "")}   # 2FA kodu (21.11.2026)


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


# build_odeme moved to checks.build_odeme — now date-selectable (last 7 days) with an
# open-balances panel (res-guest-balance-list). Still uses paycheck.classify per day.


def kart_uyarisi(weeks: list, incoming_dir: Path, sources: dict, simdi=None):
    """Haftalık kart okuması GELMEDİYSE panoda gösterilecek uyarı (yoksa None).

    18.11.2026: 16 Kasım okuması sunucuya hiç gelmedi; pano son haftayı (2–8 Kas)
    göstermeye devam etti ve kimse fark etmedi. Kural: resepsiyon her PAZARTESİ biten
    haftanın (Pzt–Paz) kilitlerini okutup gönderir. SALI 00:00'dan (TR) itibaren biten
    hafta panoda yoksa uyarı verilir. Gelen ama analiz edilemeyen dosya ayrıca söylenir.
    """
    simdi = simdi or (dt.datetime.utcnow() + dt.timedelta(hours=3))     # Türkiye saati
    bugun = simdi.date()
    bu_pzt = bugun - dt.timedelta(days=bugun.weekday())
    beklenen = bu_pzt - dt.timedelta(days=7 if bugun.weekday() >= 1 else 14)
    var = {w["lo"] for w in weeks}
    if not var:
        return None
    en_son = max(dt.date.fromisoformat(x) for x in var)
    eksik, d = [], beklenen
    while d > en_son and len(eksik) < 8:
        eksik.append(d)
        d -= dt.timedelta(days=7)
    if not eksik:
        return None
    eksik.reverse()

    def etiket(pzt):
        paz = pzt + dt.timedelta(days=6)
        if pzt.month == paz.month:
            return f"{pzt.day}–{paz.day} {TR_MONTHS[paz.month]} {paz.year}"
        return f"{pzt.day} {TR_MONTHS[pzt.month]} – {paz.day} {TR_MONTHS[paz.month]} {paz.year}"

    # Gelmiş ama analizi olmayan döküm var mı? (dosya adı = okuma tarihi; hafta =
    # okumadan önceki son Pzt–Paz — kart_yukle.week_of ile aynı kural)
    gelmis = {}
    for f in sorted(incoming_dir.glob("*.zip.enc")) if incoming_dir.is_dir() else []:
        ad = f.name.split(".")[0]
        try:
            okuma = dt.date(int(ad[:4]), int(ad[4:6]), int(ad[6:8]))
        except ValueError:
            continue
        paz = okuma - dt.timedelta(days=okuma.weekday() + 1)
        gelmis[paz - dt.timedelta(days=6)] = (f.name, f.name in sources)

    satirlar = []
    for pzt in eksik:
        g = gelmis.get(pzt)
        if g and not g[1]:
            satirlar.append(f"{etiket(pzt)}: kart dosyası GELDİ ({g[0]}) ama analizi panoda yok — "
                            "birkaç saat içinde düzelmezse analiz başarısız olmuştur (dosya yarım/eksik olabilir).")
        else:
            satirlar.append(f"{etiket(pzt)}: kart okuması sunucuya GELMEDİ.")
    return {
        "hafta_sayisi": len(eksik),
        "haftalar": [etiket(p) for p in eksik],
        "kisa": (f"{etiket(eksik[-1])} kart okuması gelmedi — bu hafta kontrol YAPILMADI"
                 if len(eksik) == 1 else
                 f"{len(eksik)} haftanın kart okuması gelmedi ({etiket(eksik[0])} → "
                 f"{etiket(eksik[-1])}) — kontrol YAPILMADI"),
        "satirlar": satirlar,
        "son_analiz": next((w["label"] for w in weeks if w["lo"] == en_son.isoformat()), ""),
    }


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

# --- Roles ---------------------------------------------------------------
# Reception sees ONLY the sections listed here; the manager (owner) sees everything.
#
# Resepsiyon YALNIZCA kendi işini gören sayfaları görür: gün sonu, günlük ödeme
# kontrolü, açık bakiye. Denetim sayfaları (kart güvenliği, iptal/silinen, indirim,
# kasa & POS) ve finans sayfaları (vergi, aylık satışlar, istatistikler)
# YÖNETİME ÖZELDİR — bunlar zaten resepsiyon kaynaklı kaçağı yakalamak için var;
# resepsiyon bunları görürse neyin yakalandığını da görmüş olur. (Sahibin kararı,
# 24.08.2026.) Bir listeyi resepsiyona açmak istersen anahtarını buraya ekle.
# Fiyat Kontrol iki role de açık: resepsiyon kapı fiyatlarını oradan görür (17.10.2026).
# Eksik Bilgiler iki role de açık: otel müdürü kontrol eder, resepsiyon da kendi
# eksiğini görüp tamamlar (20.10.2026).
RECEPTION_SECTIONS = {"gunsonu", "odeme", "bakiye", "gunluk", "kart", "tvkart", "fiyat", "eksik", "yorumkart", "odakontrol",
                      "kurumlar"}   # kurumlar: müdür işaretler (24.11.2026); yorumlar/paylasim yalnız yönetim


def passwords() -> dict:
    """Return {'manager': pw, 'reception': pw}. Manager is required; reception is
    optional (if unset, only the manager password works). Falls back to the old
    single DASH_PASSWORD as the manager password for backward compatibility."""
    mgr = (os.environ.get("DASH_PW_MANAGER")
           or os.environ.get("DASH_PASSWORD", "")).strip()
    rec = os.environ.get("DASH_PW_RECEPTION", "").strip()
    if not mgr:
        print("Yönetim şifresi yok (DASH_PW_MANAGER / DASH_PASSWORD Secret / .env).",
              file=sys.stderr)
        sys.exit(2)
    if rec and rec == mgr:
        print("UYARI: resepsiyon ve yönetim şifresi aynı — rol ayrımı olmaz.",
              file=sys.stderr)
    return {"manager": mgr, "reception": rec}


def section_passwords(key: str, pws: dict) -> list:
    """Which passwords may open section `key`. Manager always; reception only for
    RECEPTION_SECTIONS. Duplicates/blanks are dropped by encrypt_multi."""
    allowed = [pws["manager"]]
    if key in RECEPTION_SECTIONS and pws.get("reception"):
        allowed.append(pws["reception"])
    return allowed


def encrypt_section(section: dict, key: str, pws: dict) -> dict:
    keep = ("label", "count", "count_label", "tone", "sub", "updated", "html")
    payload = json.dumps({k: section.get(k) for k in keep}, ensure_ascii=False)
    return dashcrypto.encrypt_multi(payload, section_passwords(key, pws))


def write_blob(key: str, blob: dict, out_dir: Path):
    d = out_dir / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.enc.json").write_text(json.dumps(blob), encoding="utf-8")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def build_cards():
    """Local weekly: build the card-security section and commit its encrypted blob."""
    pws = passwords()
    section = build_kart()
    blob = encrypt_section(section, "kart", pws)  # manager-only
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "kart.enc.json").write_text(json.dumps(blob), encoding="utf-8")
    print(f"KART bölümü şifrelendi -> site_data/kart.enc.json "
          f"(şüpheli={section['count']}, {section['sub']})")
    print("Yayınlamak için: ./kart-yayinla.sh  (commit + push + workflow tetikler)")


def build_cloud():
    """Cloud daily: build live sections, reuse committed card blob, write public/."""
    pws = passwords()
    env = elektra_env()
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)

    import checks

    built = []

    # Live sections (Elektra API only). A broken section is logged and skipped so
    # one bad fetch never blanks the whole dashboard.
    live = (("gunsonu", build_gunsonu), ("odeme", checks.build_odeme),
            ("kasa", checks.build_kasa), ("nakit", checks.build_nakit),
            ("iptal", checks.build_iptal),
            ("indirim", checks.build_indirim), ("bakiye", checks.build_bakiye),
            ("eksik", checks.build_eksik),
            ("fiyat", checks.build_fiyat),
            ("stats", checks.build_stats), ("satis", checks.build_satis),
            ("gelirgider", checks.build_gelirgider),   # yalnız yönetim (20.11.2026)
            ("borclar", checks.build_borclar),
            ("vergi", checks.build_vergi), ("gunluk", checks.build_gunluk),
            ("tvkart", checks.build_tvkart), ("yorumkart", checks.build_yorumkart),
            ("yorumlar", pazarlama.build_yorumlar), ("paylasim", pazarlama.build_paylasim),   # Pazarlama 24.11.2026
            ("kurumlar", pazarlama.build_kurumlar),
            ("odakontrol", pazarlama.build_odakontrol),   # Oda Kontrol Listesi 27.11.2026
            ("anlik", checks.build_anlik))   # Anlık Durum — yalnız yönetim (22.11.2026; tahsilat içerir)
    for key, fn in live:
        try:
            section = fn(env)
            write_blob(key, encrypt_section(section, key, pws), PUBLIC)
            built.append(key)
            role = "resepsiyon+yönetim" if key in RECEPTION_SECTIONS else "yönetim"
            print(f"  {key}: {section['count']} {section.get('count_label','')} [{role}] ✓")
        except Exception as e:
            print(f"  {key}: ÜRETİLEMEDİ — {e}", file=sys.stderr)

    # Card section: MULTI-WEEK, manager-only. Copy every committed weekly blob + the
    # week index; the shell shows a week picker. Weeks are built locally by
    # kart_yukle.py (each already encrypted manager-only via encrypt_multi).
    kart_dir = SITE_DATA / "kart"
    kart_idx = kart_dir / "index.json"
    if kart_idx.exists():
        weeks = json.loads(kart_idx.read_text()).get("weeks", [])
        (PUBLIC / "data").mkdir(parents=True, exist_ok=True)
        n = 0
        for w in weeks:
            src = kart_dir / f"{w['id']}.enc.json"
            if src.exists():
                shutil.copyfile(src, PUBLIC / "data" / w["file"])
                n += 1
        srcs_path = kart_dir / "sources.json"
        srcs = json.loads(srcs_path.read_text()) if srcs_path.exists() else {}
        uyari = kart_uyarisi(weeks, SITE_DATA / "cardreads-incoming", srcs)
        idx_out = {"weeks": weeks}
        if uyari:
            idx_out["uyari"] = uyari
        (PUBLIC / "data" / "kart-index.json").write_text(
            json.dumps(idx_out, ensure_ascii=False), encoding="utf-8")
        if n:
            built.append("kart")
            print(f"  kart: {n} hafta kopyalandı [yönetim] ✓")
        if uyari:
            print(f"  kart: ⚠️  {uyari['kisa']} ({uyari['hafta_sayisi']} hafta eksik)")
    elif (SITE_DATA / "kart.enc.json").exists():  # eski tek-blok (geçiş)
        (PUBLIC / "data").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SITE_DATA / "kart.enc.json", PUBLIC / "data" / "kart.enc.json")
        built.append("kart")
        print("  kart: eski tek-blok kopyalandı ✓")
    else:
        print("  kart: site_data/kart/ yok — kart tile'ı atlandı "
              "(yerelde python3 kart_yukle.py <zip>)")

    if not any(k in built for k in ("gunsonu", "odeme")):
        print("HİÇBİR CANLI BÖLÜM ÜRETİLEMEDİ — yayın iptal.", file=sys.stderr)
        sys.exit(2)

    # Login shell + manifest (ordered by SECTION_ORDER, only what we actually built).
    order = [k for k in SECTION_ORDER if k in built]
    shutil.copyfile(SHELL, PUBLIC / "index.html")
    # Marka dosyaları (Bilsa logosu). Göreli yoldan sunulur: alan adı değişse
    # (ör. rivaalsancak.bilsa.com.tr) hiçbir şey düzenlenmeden orada da çalışır.
    if (ROOT / "assets").is_dir():
        shutil.copytree(ROOT / "assets", PUBLIC / "assets", dirs_exist_ok=True)
    # TV kullanım kartları: indirilebilir PDF/PNG (odaya konan misafir kartları, gizli
    # değil). Üretici betik, ara HTML ve ham görseller yayına çıkmaz.
    if (ROOT / "kartlar" / "tv-kumanda").is_dir():
        shutil.copytree(ROOT / "kartlar" / "tv-kumanda", PUBLIC / "kartlar" / "tv-kumanda",
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.py", "*.html", "img", ".tmp-*", "__pycache__"))
    # Google yorum kartları (16.11.2026): basılı misafir kartı, gizli değil.
    # Oda kontrol listesi (27.11.2026): kat hizmetleri formu, gizli değil.
    if (ROOT / "kartlar" / "oda-kontrol").is_dir():
        shutil.copytree(ROOT / "kartlar" / "oda-kontrol", PUBLIC / "kartlar" / "oda-kontrol", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.py", "*.html", "__pycache__"))
    if (ROOT / "kartlar" / "yorum").is_dir():
        shutil.copytree(ROOT / "kartlar" / "yorum", PUBLIC / "kartlar" / "yorum",
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.py", "*.html", "img", ".tmp-*", "__pycache__"))
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
