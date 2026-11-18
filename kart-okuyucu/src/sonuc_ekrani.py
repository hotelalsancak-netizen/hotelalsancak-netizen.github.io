# -*- coding: utf-8 -*-
"""
sonuc_ekrani  -  KartKayitGonder'in TAM EKRAN sonuc penceresi

18.11.2026: 16 Kasim okumasi sunucuya hic gitmedi ama kimse fark etmedi; program
sonucu siyah pencerede kucuk bir satirla yaziyordu. Artik islem bitince ekranin
TAMAMINI kaplayan bir pencere acilir:

    KIRMIZI  ->  GONDERILEMEDI   (ne oldu, neden, ne yapilmali)
    TURUNCU  ->  GONDERILDI ama dikkat edilecek bir sey var
    YESIL    ->  GONDERILDI      (kac oda, hangi hafta, panoda ne zaman)

Kirmizi pencere ancak "OKUDUM - KAPAT" dugmesiyle kapanir (Esc ile kapanmaz),
digerleri Esc / Enter ile de kapanir. Pencere acilamazsa (tkinter yoksa vb.)
Windows'un kendi uyari kutusu, o da olmazsa konsol kullanilir - sonuc hicbir
durumda sessizce kaybolmaz. Her sonuc ayrica C:\\OdaKartOku\\log\\sonuc.txt'e yazilir.
"""

import datetime
import os

RENKLER = {
    "basarisiz": "#B71C1C",
    "uyari": "#E65100",
    "basarili": "#1B5E20",
}
BASLIK_IKON = {"basarisiz": "\u2716", "uyari": "\u26A0", "basarili": "\u2714"}


def _log_yaz(durum, baslik, aciklama, ayrintilar):
    for kok in (r"C:\OdaKartOku\log", os.path.join(os.path.expanduser("~"), "OdaKartOku-log")):
        try:
            os.makedirs(kok, exist_ok=True)
            with open(os.path.join(kok, "sonuc.txt"), "a", encoding="utf-8") as f:
                f.write("{}  {}  {}\n".format(
                    datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                    durum.upper(), baslik))
                for s in [aciklama] + list(ayrintilar or []):
                    if s:
                        f.write("      " + s.replace("\n", "\n      ") + "\n")
            return
        except Exception:
            continue


def _konsol(durum, baslik, aciklama, ayrintilar, yapilacaklar):
    cizgi = "#" * 62
    print("\n" + cizgi)
    print("#  {}".format(baslik))
    print(cizgi)
    if aciklama:
        print(aciklama)
    for s in ayrintilar or []:
        print("  " + s)
    if yapilacaklar:
        print("\nYAPILACAKLAR:")
        for i, s in enumerate(yapilacaklar, 1):
            print("  {}) {}".format(i, s))
    print(cizgi + "\n", flush=True)


def _windows_kutusu(durum, baslik, metin):
    try:
        import ctypes
        ikon = {"basarisiz": 0x10, "uyari": 0x30, "basarili": 0x40}[durum]
        # MB_OK | ikon | MB_SYSTEMMODAL(0x1000) | MB_SETFOREGROUND(0x10000) | MB_TOPMOST(0x40000)
        ctypes.windll.user32.MessageBoxW(None, metin, baslik, ikon | 0x1000 | 0x10000 | 0x40000)
        return True
    except Exception:
        return False


def goster(durum, baslik, aciklama="", ayrintilar=None, yapilacaklar=None, alt_bilgi=""):
    """
    durum       : "basarisiz" | "uyari" | "basarili"
    baslik      : kocaman yazilacak tek satir  (orn. "YUKLEME BASARISIZ")
    aciklama    : basligin altindaki buyuk cumle (ne oldu)
    ayrintilar  : orta boy satirlar (neden, oda listesi, hata kodu...)
    yapilacaklar: numarali "ne yapmali" adimlari
    alt_bilgi   : en altta kucuk satir (tarih, klasor, hafta)
    """
    ayrintilar = [s for s in (ayrintilar or []) if s]
    yapilacaklar = [s for s in (yapilacaklar or []) if s]
    _log_yaz(durum, baslik, aciklama, ayrintilar + ["YAPILACAK: " + s for s in yapilacaklar])
    _konsol(durum, baslik, aciklama, ayrintilar, yapilacaklar)

    try:
        import tkinter as tk
    except Exception:
        tk = None

    if tk is not None:
        try:
            _pencere(tk, durum, baslik, aciklama, ayrintilar, yapilacaklar, alt_bilgi)
            return
        except Exception as e:                     # ekran yoksa, tk bozuksa...
            print("(Tam ekran pencere acilamadi: {})".format(e), flush=True)

    metin = "\n\n".join(x for x in [
        aciklama,
        "\n".join(ayrintilar),
        "\n".join("{}) {}".format(i, s) for i, s in enumerate(yapilacaklar, 1)),
        alt_bilgi] if x)
    _windows_kutusu(durum, baslik, metin)


def _pencere(tk, durum, baslik, aciklama, ayrintilar, yapilacaklar, alt_bilgi):
    renk = RENKLER[durum]
    kok = tk.Tk()
    kok.title(baslik)
    kok.configure(bg=renk)
    try:
        kok.attributes("-fullscreen", True)
    except Exception:
        kok.state("zoomed")
    kok.attributes("-topmost", True)

    gen = kok.winfo_screenwidth()
    yuk = kok.winfo_screenheight()
    olcek = min(gen / 1920.0, yuk / 1080.0)
    def px(n):                               # tk'de negatif boyut = piksel
        return -max(12, int(n * olcek))
    sar = int(gen * 0.90)

    cerceve = tk.Frame(kok, bg=renk)
    cerceve.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(cerceve, text=BASLIK_IKON[durum] + "  " + baslik, bg=renk, fg="white",
             font=("Segoe UI", px(150 if len(baslik) <= 16 else 115), "bold"),
             wraplength=sar, justify="center").pack(pady=(0, int(20 * olcek)))

    if aciklama:
        tk.Label(cerceve, text=aciklama, bg=renk, fg="white",
                 font=("Segoe UI", px(54), "bold"), wraplength=sar,
                 justify="center").pack(pady=(0, int(25 * olcek)))

    if ayrintilar:
        tk.Label(cerceve, text="\n".join(ayrintilar), bg=renk, fg="#FFF3E0",
                 font=("Segoe UI", px(38)), wraplength=sar,
                 justify="center").pack(pady=(0, int(25 * olcek)))

    if yapilacaklar:
        kutu = tk.Frame(cerceve, bg="white", padx=int(30 * olcek), pady=int(18 * olcek))
        kutu.pack(pady=(0, int(25 * olcek)))
        tk.Label(kutu, text="NE YAPMALI?", bg="white", fg=renk,
                 font=("Segoe UI", px(40), "bold")).pack(anchor="w")
        tk.Label(kutu, bg="white", fg="#212121", justify="left",
                 wraplength=int(gen * 0.82), font=("Segoe UI", px(34)),
                 text="\n".join("{}) {}".format(i, s) for i, s in enumerate(yapilacaklar, 1))
                 ).pack(anchor="w")

    kapat_yazi = "OKUDUM  -  KAPAT" if durum == "basarisiz" else "KAPAT"
    tk.Button(cerceve, text=kapat_yazi, command=kok.destroy,
              font=("Segoe UI", px(44), "bold"), bg="white", fg=renk,
              activebackground="#EEEEEE", relief="flat",
              padx=int(50 * olcek), pady=int(12 * olcek)).pack(pady=(int(10 * olcek), 0))

    if alt_bilgi:
        tk.Label(kok, text=alt_bilgi, bg=renk, fg="#FFCDD2" if durum == "basarisiz" else "#E8F5E9",
                 font=("Segoe UI", px(24))).place(relx=0.5, rely=0.98, anchor="s")

    if durum != "basarisiz":                 # kirmizi ekran tusla gecistirilemesin
        kok.bind("<Escape>", lambda e: kok.destroy())
        kok.bind("<Return>", lambda e: kok.destroy())

    def one_getir():
        try:
            kok.lift()
            kok.focus_force()
            kok.attributes("-topmost", True)
        except Exception:
            pass
    kok.after(300, one_getir)
    for i in range(3 if durum == "basarisiz" else 1):
        kok.after(400 + i * 700, kok.bell)
    kok.mainloop()
