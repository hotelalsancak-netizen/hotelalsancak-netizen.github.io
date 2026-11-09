// OdaKartOku - Kale Kilit "Kilit acilis kayitlari" ekranindan
// el terminalindeki tum odalarin kayitlarini otomatik okuyup PDF olarak kaydeder.
//
// Derleme:
//   C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /target:exe /platform:x86 ^
//     /out:C:\OdaKartOku\OdaKartOku.exe C:\OdaKartOku\src\OdaKartOku.cs
//
// NOT: Kaynak dosya UTF-8 BOM ile kaydedilmelidir (Turkce karakterler icin).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace OdaKartOku
{
    #region Win32

    internal static class Win32
    {
        public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
        [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr l);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
        [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
        [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
        [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
        [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
        [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
        [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
        [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
        [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
        [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);

        // --- acilir menu (popup menu) islemleri ---
        [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr hMenu);
        [DllImport("user32.dll")] public static extern int GetMenuItemID(IntPtr hMenu, int nPos);
        [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetMenuStringW")]
        public static extern int GetMenuString(IntPtr hMenu, int uIDItem, StringBuilder lp, int cch, uint flags);
        [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hWnd, IntPtr hMenu, int uItem, out RECT r);

        // --- gercek fare girisi (acilir menuler yalnizca bunu dinler) ---
        [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
        [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
        [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);

        [StructLayout(LayoutKind.Sequential)]
        public struct POINT { public int X, Y; }

        public const uint MN_GETHMENU = 0x01E1;
        public const uint MF_BYPOSITION = 0x0400;
        public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        public const uint MOUSEEVENTF_LEFTUP = 0x0004;

        /// <summary>Ekranda belirtilen noktaya GERCEK fare tiklamasi yapar.
        /// Acilir menuler gonderilen mesajlari yok sayar, yalnizca bunu gorur.
        /// Imlecin eski yeri geri konur.</summary>
        public static void GercekTikla(int ekranX, int ekranY)
        {
            POINT eski;
            GetCursorPos(out eski);
            SetCursorPos(ekranX, ekranY);
            Thread.Sleep(120);
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, IntPtr.Zero);
            Thread.Sleep(60);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, IntPtr.Zero);
            Thread.Sleep(120);
            SetCursorPos(eski.X, eski.Y);
        }

        public const int SW_SHOW = 5;
        public const int SW_RESTORE = 9;

        [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW")]
        public static extern IntPtr SendMessageTimeout(IntPtr h, uint m, IntPtr w, IntPtr l, uint f, uint t, out IntPtr r);

        [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode)]
        public static extern IntPtr SendMessageTimeoutSB(IntPtr h, uint m, IntPtr w, StringBuilder l, uint f, uint t, out IntPtr r);

        [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode)]
        public static extern IntPtr SendMessageTimeoutStr(IntPtr h, uint m, IntPtr w, string l, uint f, uint t, out IntPtr r);

        [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a, bool inh, int pid);
        [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
        [DllImport("kernel32.dll")] public static extern IntPtr VirtualAllocEx(IntPtr p, IntPtr a, IntPtr sz, uint t, uint pr);
        [DllImport("kernel32.dll")] public static extern bool VirtualFreeEx(IntPtr p, IntPtr a, IntPtr sz, uint t);
        [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr p, IntPtr a, byte[] buf, int sz, out IntPtr read);

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT { public int Left, Top, Right, Bottom; }

        // Mesajlar
        public const uint WM_CLOSE = 0x0010;
        public const uint WM_SETTEXT = 0x000C;
        public const uint WM_GETTEXT = 0x000D;
        public const uint WM_GETTEXTLENGTH = 0x000E;
        public const uint WM_COMMAND = 0x0111;
        public const uint WM_MOUSEMOVE = 0x0200;
        public const uint WM_LBUTTONDOWN = 0x0201;
        public const uint WM_LBUTTONUP = 0x0202;
        public const uint WM_CHAR = 0x0102;

        public const uint BM_CLICK = 0x00F5;
        public const uint BM_GETCHECK = 0x00F0;

        public const uint CB_GETCOUNT = 0x0146;
        public const uint CB_GETCURSEL = 0x0147;
        public const uint CB_SETCURSEL = 0x014E;
        public const uint CB_GETLBTEXT = 0x0148;

        public const uint EM_SETSEL = 0x00B1;

        public const uint TB_BUTTONCOUNT = 1048;   // WM_USER + 24
        public const uint TB_GETITEMRECT = 1053;   // WM_USER + 29

        public const uint SMTO_ABORTIFHUNG = 0x0002;

        // ---- yardimcilar ----

        public static string ClassOf(IntPtr h)
        {
            var sb = new StringBuilder(256);
            GetClassName(h, sb, 256);
            return sb.ToString();
        }

        public static string TitleOf(IntPtr h)
        {
            var sb = new StringBuilder(1024);
            GetWindowTextW(h, sb, 1024);
            return sb.ToString();
        }

        /// <summary>Kontrolun metnini WM_GETTEXT ile okur (surecler arasi calisir).</summary>
        public static string ControlText(IntPtr h)
        {
            IntPtr res;
            if (SendMessageTimeout(h, WM_GETTEXTLENGTH, IntPtr.Zero, IntPtr.Zero,
                                   SMTO_ABORTIFHUNG, 4000, out res) == IntPtr.Zero)
                return null;                       // yanit yok
            int len = res.ToInt32();
            if (len <= 0) return string.Empty;
            var sb = new StringBuilder(len + 4);
            SendMessageTimeoutSB(h, WM_GETTEXT, new IntPtr(len + 1), sb,
                                 SMTO_ABORTIFHUNG, 6000, out res);
            return sb.ToString();
        }

        public static int? Send(IntPtr h, uint msg, IntPtr wp, IntPtr lp, uint timeout = 4000)
        {
            IntPtr res;
            if (SendMessageTimeout(h, msg, wp, lp, SMTO_ABORTIFHUNG, timeout, out res) == IntPtr.Zero)
                return null;
            return res.ToInt32();
        }

        public static List<IntPtr> TopWindows(int pid)
        {
            var list = new List<IntPtr>();
            EnumWindows((h, l) =>
            {
                uint p;
                GetWindowThreadProcessId(h, out p);
                if (p == (uint)pid && IsWindowVisible(h)) list.Add(h);
                return true;
            }, IntPtr.Zero);
            return list;
        }

        /// <summary>Gizli pencereler dahil TUM ust pencereler.
        /// Program simge durumundayken veya giris yapilmamisken ana form
        /// gizli oldugu icin gerekli.</summary>
        public static List<IntPtr> TumUstPencereler(int pid)
        {
            var list = new List<IntPtr>();
            EnumWindows((h, l) =>
            {
                uint p;
                GetWindowThreadProcessId(h, out p);
                if (p == (uint)pid) list.Add(h);
                return true;
            }, IntPtr.Zero);
            return list;
        }

        public static List<IntPtr> Children(IntPtr parent)
        {
            var list = new List<IntPtr>();
            EnumChildWindows(parent, (h, l) => { list.Add(h); return true; }, IntPtr.Zero);
            return list;
        }

        /// <summary>VCL kontrollerine gercek fare tiklamasi gonderir. Pencerenin on planda
        /// olmasi GEREKMEZ - BM_CLICK ozel cizimli VCL kontrollerinde calismaz, bu calisir.</summary>
        public static void MouseClick(IntPtr h, int clientX = -1, int clientY = -1)
        {
            RECT r;
            GetWindowRect(h, out r);
            int cx = clientX >= 0 ? clientX : (r.Right - r.Left) / 2;
            int cy = clientY >= 0 ? clientY : (r.Bottom - r.Top) / 2;
            IntPtr lp = new IntPtr((cy << 16) | (cx & 0xFFFF));
            // Iki kez WM_MOUSEMOVE: ortak denetim araç çubuklari "sicak oge"yi
            // belirlemeden gelen tiklamayi yok sayabiliyor.
            PostMessage(h, WM_MOUSEMOVE, IntPtr.Zero, lp);
            Thread.Sleep(45);
            PostMessage(h, WM_MOUSEMOVE, IntPtr.Zero, lp);
            Thread.Sleep(35);
            PostMessage(h, WM_LBUTTONDOWN, new IntPtr(1), lp);
            Thread.Sleep(45);
            PostMessage(h, WM_LBUTTONUP, IntPtr.Zero, lp);
        }
    }

    #endregion

    #region Gunluk

    internal static class Log
    {
        private static StreamWriter _w;

        public static void Baslat(string dosya)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(dosya));
                _w = new StreamWriter(dosya, true, new UTF8Encoding(true));
                _w.AutoFlush = true;
                _w.WriteLine();
                _w.WriteLine("======== " + DateTime.Now.ToString("dd.MM.yyyy HH:mm:ss") + " ========");
            }
            catch { _w = null; }
        }

        public static void Yaz(string s)
        {
            Console.WriteLine(s);
            if (_w != null) { try { _w.WriteLine(DateTime.Now.ToString("HH:mm:ss") + "  " + s); } catch { } }
        }

        public static void Sadece(string s)   // sadece dosyaya
        {
            if (_w != null) { try { _w.WriteLine(DateTime.Now.ToString("HH:mm:ss") + "  " + s); } catch { } }
        }

        public static void Kapat()
        {
            if (_w != null) { try { _w.Flush(); _w.Dispose(); } catch { } _w = null; }
        }
    }

    #endregion

    internal class OdaSonuc
    {
        public int Sira;
        public string OdaNo;
        public bool Basarili;
        public string Hata;
        public long Boyut;
    }

    internal class Program
    {
        // ---- Kale Kilit pencere sinifi adlari ----
        const string CLS_ANA = "TMainFrm";
        const string CLS_GIRIS = "TLogInFrm";

        // Kale Kilit kapaliysa buradan baslatilir
        const string KALE_EXE =
            @"C:\Net_kale_5.0.10.25_green\Net_kale_5.0.10.25_green\Hotel_N_kale.exe";

        // Otomatik giris bilgileri (/kullanici: ve /sifre: ile degistirilebilir)
        static string _kullanici = "ADMIN";
        static string _sifre = "";   // GİZLİ — Kale Kilit operatör şifresi; gerçek değer yalnız resepsiyondaki kopyada, repoya YAZMAYIN
        const string CLS_FRAME = "TSearchOpenDoorRecordsFrame";
        const string CLS_ONIZLEME = "TfrxPreviewForm";
        const string CLS_EXPORT = "TfrxPDFExportDialog";
        const string CLS_ILERLEME = "TProgressFrm";
        const string CLS_TOOLBAR = "TToolBar";
        const string CLS_DIYALOG = "#32770";

        const int PDF_BUTON_INDEX = 3;      // onizleme araç çubuğunda Adobe PDF ikonu
        const int KUCUK_PDF_SINIRI = 15000; // bu boyutun altindaki PDF supheli kabul edilir
        const int ARDISIK_BOS_SINIRI = 10;  // bu kadar sira ust uste bos gelirse durulur

        // Sol ana menu (TRzToolbar) olculeri - istemci koordinatlari
        const int MENU_X = 100;             // oge metninin ortasi
        const int MENU_ILK_Y = 26;          // 1. ogenin merkezi
        const int MENU_ARALIK = 48;         // ogeler arasi mesafe
        const int MENU_KAYIT_ARAMA = 3;     // 0-tabanli: Kayıt arama 4. sirada
        const int ALTMENU_KILIT_ACILIS = 3; // 0-tabanli: Kilit açılış kayıtları 4. sirada
        const int ALTMENU_OGE_SAYISI = 7;

        static int _pid;
        static IntPtr _ana;
        static bool _sadeceMenu;    // sadece ekrana gitmeyi test et, okuma yapma
        static bool _tumunuOku;     // zaten alinmis odalari da bastan oku

        // Hangi sirada hangi oda var? Onceki calistirmalardan ogrenilir.
        // Boylece yarim kalan bir gunu tamamlarken alinmis odalar tekrar okunmaz.
        const string SIRA_ODA_DOSYA = @"C:\OdaKartOku\sira_oda.txt";
        static readonly Dictionary<int, string> _siraOda = new Dictionary<int, string>();

        static int Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;
            Console.Title = "OdaKartOku - Kale Kilit Otomatik Kayit Okuma";

            int ilk = 1, son = 55;
            string klasor = null;
            bool bekle = true;
            bool yukle = false, sadeceYukle = false;
            string jetonKaydet = null;

            foreach (var a in args)
            {
                if (a.StartsWith("/ilk:", StringComparison.OrdinalIgnoreCase)) int.TryParse(a.Substring(5), out ilk);
                else if (a.StartsWith("/son:", StringComparison.OrdinalIgnoreCase)) int.TryParse(a.Substring(5), out son);
                else if (a.StartsWith("/klasor:", StringComparison.OrdinalIgnoreCase)) klasor = a.Substring(8).Trim('"');
                else if (a.StartsWith("/jeton:", StringComparison.OrdinalIgnoreCase)) jetonKaydet = a.Substring(7).Trim('"');
                else if (a.Equals("/beklemeden", StringComparison.OrdinalIgnoreCase)) bekle = false;
                else if (a.StartsWith("/kullanici:", StringComparison.OrdinalIgnoreCase)) _kullanici = a.Substring(11).Trim('"');
                else if (a.StartsWith("/sifre:", StringComparison.OrdinalIgnoreCase)) _sifre = a.Substring(7).Trim('"');
                else if (a.Equals("/sadecemenu", StringComparison.OrdinalIgnoreCase)) _sadeceMenu = true;
                else if (a.Equals("/tumunu", StringComparison.OrdinalIgnoreCase)) _tumunuOku = true;
                else if (a.Equals("/yukle", StringComparison.OrdinalIgnoreCase)) yukle = true;
                else if (a.Equals("/sadeceyukle", StringComparison.OrdinalIgnoreCase)) { yukle = true; sadeceYukle = true; }
            }

            if (klasor == null)
            {
                string masaustu = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                klasor = Path.Combine(masaustu, DateTime.Now.ToString("dd.MM.yyyy"));
            }

            Log.Baslat(Path.Combine(KOK, "log", "odakartoku.log"));

            // --- jeton kaydetme modu ---
            if (jetonKaydet != null)
            {
                try
                {
                    Jeton.Kaydet(Path.Combine(KOK, "jeton.dat"), jetonKaydet);
                    Console.WriteLine("Erisim jetonu SIFRELI olarak kaydedildi:");
                    Console.WriteLine("  " + Path.Combine(KOK, "jeton.dat"));
                    Console.WriteLine("  (Yalnizca bu Windows kullanicisi cozebilir - DPAPI)");
                    if (!File.Exists(Path.Combine(KOK, "ayarlar.ini")))
                    {
                        Ayarlar.OrnekOlustur(Path.Combine(KOK, "ayarlar.ini"));
                        Console.WriteLine("Ornek ayar dosyasi olusturuldu: " + Path.Combine(KOK, "ayarlar.ini"));
                    }
                }
                catch (Exception ex) { Console.WriteLine("HATA: " + ex.Message); return 1; }
                if (bekle) { Console.WriteLine("Kapatmak icin bir tusa basin..."); try { Console.ReadKey(true); } catch { } }
                return 0;
            }

            Yazdir("=====================================================");
            Yazdir("   ODA KART OKU - Kale Kilit Otomatik Kayit Alma");
            Yazdir("=====================================================");
            Yazdir("");
            Log.Yaz("Hedef klasor : " + klasor);
            Log.Yaz("Oda sirasi   : " + ilk + " - " + son);
            Yazdir("");

            int cikis = 0;
            try
            {
                if (!sadeceYukle) cikis = Calistir(ilk, son, klasor);
                if (yukle) { int yc = ZipleVeYukle(klasor); if (cikis == 0) cikis = yc; }
            }
            catch (Exception ex)
            {
                Log.Yaz("");
                Log.Yaz("!!! BEKLENMEYEN HATA: " + ex.Message);
                Log.Sadece(ex.ToString());
                cikis = 9;
            }
            finally
            {
                Log.Kapat();
            }

            if (bekle)
            {
                Console.WriteLine();
                Console.WriteLine("Kapatmak icin bir tusa basin...");
                try { Console.ReadKey(true); } catch { }
            }
            return cikis;
        }

        static void Yazdir(string s) { Console.WriteLine(s); }

        const string KOK = @"C:\OdaKartOku";

        // =============================================================
        /// <summary>Gunun klasorunu zipler ve GitHub/GitLab'a yukler.</summary>
        static int ZipleVeYukle(string klasor)
        {
            Yazdir("");
            Yazdir("-----------------------------------------------------");
            Log.Yaz("ZIPLEME VE YUKLEME");

            string ayarDosya = Path.Combine(KOK, "ayarlar.ini");
            string jetonDosya = Path.Combine(KOK, "jeton.dat");

            if (!File.Exists(ayarDosya))
            {
                Ayarlar.OrnekOlustur(ayarDosya);
                Log.Yaz("Ayar dosyasi yoktu, ornek olusturuldu: " + ayarDosya);
                Log.Yaz("Lutfen icini doldurup tekrar deneyin.");
                return 20;
            }

            string jeton = Jeton.Oku(jetonDosya);
            if (string.IsNullOrEmpty(jeton))
            {
                Log.Yaz("HATA: Erisim jetonu kayitli degil.");
                Log.Yaz("  Once su komutu bir kez calistirin:");
                Log.Yaz("     OdaKartOku.exe /jeton:BURAYA_TOKEN_YAZIN");
                return 21;
            }

            var ayar = Ayarlar.Yukle(ayarDosya);
            string hata;

            string zip = Yukleyici.Ziple(klasor, Path.Combine(KOK, "gonderi"), out hata);
            if (zip == null) { Log.Yaz("HATA: Zip olusturulamadi - " + hata); return 22; }
            Log.Yaz("Zip olusturuldu: " + zip + "  (" + (new FileInfo(zip).Length / 1024) + " KB)");

            Log.Yaz("Yukleniyor (" + ayar.Al("platform", "github") + ")...");
            if (!Yukleyici.Yukle(zip, ayar, jeton, out hata))
            {
                Log.Yaz("HATA: Yukleme basarisiz - " + hata);
                return 23;
            }
            Log.Yaz("YUKLEME BASARILI.");
            return 0;
        }

        // =============================================================
        static int Calistir(int ilk, int son, string klasor)
        {
            // ---- 1) Program calisiyor mu; degilse baslat ----
            var pr = Process.GetProcessesByName("Hotel_N_kale");
            if (pr.Length == 0)
            {
                Log.Yaz("Kale Kilit calismiyor, baslatiliyor...");
                if (!File.Exists(KALE_EXE))
                {
                    Log.Yaz("HATA: Kale Kilit bulunamadi: " + KALE_EXE);
                    Log.Yaz("      Masaustundeki 'Kale Kilit' kisayolunu elle calistirin.");
                    return 1;
                }
                try
                {
                    var psi = new ProcessStartInfo(KALE_EXE)
                    {
                        WorkingDirectory = Path.GetDirectoryName(KALE_EXE),
                        UseShellExecute = true,
                    };
                    Process.Start(psi);
                }
                catch (Exception ex)
                {
                    Log.Yaz("HATA: Kale Kilit baslatilamadi: " + ex.Message);
                    return 1;
                }

                // acilmasini bekle
                for (int i = 0; i < 120 && pr.Length == 0; i++)
                {
                    Thread.Sleep(500);
                    pr = Process.GetProcessesByName("Hotel_N_kale");
                }
                if (pr.Length == 0) { Log.Yaz("HATA: Kale Kilit acilmadi."); return 1; }
            }
            _pid = pr[0].Id;
            Log.Yaz("Kale Kilit bulundu (PID " + _pid + ").");

            // Formlarin olusmasini bekle. Program yeni acildiysa ana form ve giris
            // formu birkac saniye sonra ortaya cikar - sabit bekleme yeterli degil.
            {
                var basF = DateTime.Now;
                bool formVar = false;
                while ((DateTime.Now - basF).TotalSeconds < 90)
                {
                    foreach (var h in Win32.TumUstPencereler(_pid))
                    {
                        string k = Win32.ClassOf(h);
                        if (k == CLS_ANA || k == CLS_GIRIS) { formVar = true; break; }
                    }
                    if (formVar) break;
                    Thread.Sleep(400);
                }
                if (!formVar)
                {
                    Log.Yaz("HATA: Kale Kilit pencereleri 90 saniyede olusmadi.");
                    return 2;
                }
                Thread.Sleep(800);   // formun tam yerlesmesi icin kisa pay
            }

            // ---- 2) Ana pencere / oturum ----
            // Kale Kilit yeni acildiginda ONCE sadece giris formu olusur;
            // ana pencere giris yapildiktan sonra ortaya cikar. Bu yuzden
            // ana pencerenin var olmasini sart kosmuyoruz.
            _ana = AnaPencereBul();

            // SADECE gercekten simge durumuna kucultulmusse geri getir.
            // Pencere "gorunmez" ise ona ShowWindow gondermek YANLIS olur:
            // uygulama oturum acilmadigi icin gizlemistir; zorla gosterince
            // ic ekran cercevesi gizli kalir ve kontroller bulunamaz.
            if (_ana != IntPtr.Zero && Win32.IsIconic(_ana))
            {
                Log.Yaz("Kale Kilit simge durumunda, geri getiriliyor...");
                Win32.ShowWindow(_ana, Win32.SW_RESTORE);
                for (int i = 0; i < 30 && Win32.IsIconic(_ana); i++) Thread.Sleep(100);
            }

            // Ana ekran hazir degilse oturum acilmamistir -> OTOMATIK GIRIS
            if (_ana == IntPtr.Zero || !Win32.IsWindowVisible(_ana))
            {
                Log.Yaz("Oturum acilmamis, otomatik giris yapiliyor (" + _kullanici + ")...");
                string girisHata;
                if (!OtomatikGiris(out girisHata))
                {
                    Log.Yaz("");
                    Log.Yaz("HATA: Kale Kilit'e otomatik giris yapilamadi.");
                    Log.Yaz("      (" + girisHata + ")");
                    Log.Yaz("");
                    Log.Yaz("  Lutfen Kale Kilit'te elle giris yapip programi tekrar calistirin.");
                    return 7;
                }

                // giristen sonra ana ekranin acilmasini bekle
                var basG = DateTime.Now;
                while ((DateTime.Now - basG).TotalSeconds < 90)
                {
                    _ana = AnaPencereBul();
                    if (_ana != IntPtr.Zero && Win32.IsWindowVisible(_ana)) break;
                    Thread.Sleep(300);
                }
                if (_ana == IntPtr.Zero || !Win32.IsWindowVisible(_ana))
                {
                    Log.Yaz("HATA: Giristen sonra ana ekran acilmadi.");
                    return 7;
                }
                Thread.Sleep(1500);   // ana ekranin tam yerlesmesi icin
                Log.Yaz("Giris basarili, ana ekran acildi.");
            }

            // ---- 2b-once) Zararsiz bilgi/ipucu/hata pencerelerini kapat ----
            // Kale Kilit acilista "Tuyolar" penceresi gosterebiliyor. Bu bir islem
            // degildir; acik kalirsa hem menu tiklamalarini engeller hem de asagidaki
            // "baska islem acik" kontrolunu bosu bosuna tetikler.
            ArtikDiyaloglariTemizle();

            // ---- 2b) Baska bir islem acik mi (kart basma vb.) ----
            if (!Win32.IsWindowEnabled(_ana))
            {
                Log.Yaz("");
                Log.Yaz("HATA: Kale Kilit'te su anda baska bir islem acik.");
                foreach (var h in Win32.TopWindows(_pid))
                {
                    string k = Win32.ClassOf(h);
                    if (k != CLS_ANA && k != "TApplication" && Win32.IsWindowEnabled(h))
                        Log.Yaz("      Acik pencere: " + k + "  " + Win32.TitleOf(h));
                }
                Log.Yaz("");
                Log.Yaz("  Lutfen once o islemi tamamlayin veya kapatin,");
                Log.Yaz("  sonra bu programi tekrar calistirin.");
                return 6;
            }

            // ---- 2d) Ekranda kalmis bilgi/ipucu pencerelerini kapat ----
            // Kale Kilit acilista "Tuyolar" penceresi gosterebiliyor; acik kalirsa
            // menu tiklamalari ise yaramiyor.
            ArtikDiyaloglariTemizle();

            // ---- 2c) Dogru ekran acik mi, degilse menuden git ----
            IntPtr frame = FrameBul();
            if (frame == IntPtr.Zero)
            {
                Log.Yaz("Dogru ekran acik degil, menuden aciliyor...");
                string navHata;
                if (!EkranaGit(out navHata))
                {
                    Log.Yaz("");
                    Log.Yaz("HATA: 'Kilit acilis kayitlari' ekrani otomatik acilamadi.");
                    Log.Yaz("      (" + navHata + ")");
                    Log.Yaz("");
                    Log.Yaz("  Lutfen Kale Kilit programinda su menuyu elle acin:");
                    Log.Yaz("      Kayit arama  ->  Kilit acilis kayitlari");
                    Log.Yaz("");
                    Log.Yaz("  Ekrani actiktan sonra bu programi tekrar calistirin.");
                    return 3;
                }
                frame = FrameBul();
                if (frame == IntPtr.Zero) { Log.Yaz("HATA: Ekran acildi ama tanimlanamadi."); return 3; }
                Log.Yaz("Ekran menuden basariyla acildi.");
            }
            Log.Yaz("'Kilit acilis kayitlari' ekrani aktif.");

            if (_sadeceMenu) { Log.Yaz("(/sadecemenu) Menu testi tamamlandi, okuma yapilmadi."); return 0; }

            // ---- 3) Kontrolleri bul ----
            // Ekran menuden yeni acildiginda kontroller birkac saniye sonra
            // olusabiliyor; hepsi bulunana kadar tekrar tekrar ariyoruz.
            IntPtr usbRadio = IntPtr.Zero, odaCombo = IntPtr.Zero,
                   okuBtn = IntPtr.Zero, yazdirBtn = IntPtr.Zero, memo = IntPtr.Zero;

            var basK = DateTime.Now;
            while ((DateTime.Now - basK).TotalSeconds < 20)
            {
                usbRadio = odaCombo = okuBtn = yazdirBtn = memo = IntPtr.Zero;

                foreach (var c in Win32.Children(_ana))
                {
                    string k = Win32.ClassOf(c);
                    string t = Win32.TitleOf(c);
                    Win32.RECT r; Win32.GetWindowRect(c, out r);

                    if (k == "TRzRadioButton" && t == "USB") usbRadio = c;
                    // ASCII onek: Turkce karakter kodlama sorunlarindan etkilenmez
                    else if (k == "TRzBitBtn" && t.StartsWith("Kay", StringComparison.Ordinal)) okuBtn = c;
                    else if (k == "TRzBitBtn" && t.StartsWith("Yazd", StringComparison.Ordinal)) yazdirBtn = c;
                    else if (k == "TRzComboBox")
                    {
                        int? n = Win32.Send(c, Win32.CB_GETCOUNT, IntPtr.Zero, IntPtr.Zero);
                        if (n.HasValue && n.Value >= 100) odaCombo = c;   // 500 ogeli oda listesi
                    }
                    else if (k == "TRzMemo" && (r.Bottom - r.Top) > 300) memo = c;
                }

                if (usbRadio != IntPtr.Zero && odaCombo != IntPtr.Zero && okuBtn != IntPtr.Zero &&
                    yazdirBtn != IntPtr.Zero && memo != IntPtr.Zero) break;

                Thread.Sleep(400);
            }

            if (usbRadio == IntPtr.Zero || odaCombo == IntPtr.Zero || okuBtn == IntPtr.Zero ||
                yazdirBtn == IntPtr.Zero || memo == IntPtr.Zero)
            {
                Log.Yaz("HATA: Ekrandaki kontroller taninamadi.");
                Log.Yaz("  USB=" + usbRadio + " Oda=" + odaCombo + " Oku=" + okuBtn +
                        " Yazdir=" + yazdirBtn + " Memo=" + memo);
                Log.Yaz("");
                Log.Yaz("  Kale Kilit penceresi kucultulmus veya ekran tam yuklenmemis olabilir.");
                Log.Yaz("  Pencereyi buyutup programi tekrar calistirin.");
                return 4;
            }
            Log.Sadece("Kontroller: USB=" + usbRadio + " Combo=" + odaCombo + " Oku=" + okuBtn +
                       " Yazdir=" + yazdirBtn + " Memo=" + memo);

            // ---- 4) USB secili mi ----
            int? chk = Win32.Send(usbRadio, Win32.BM_GETCHECK, IntPtr.Zero, IntPtr.Zero);
            if (chk != 1)
            {
                Log.Yaz("USB secenegi isaretleniyor...");
                Win32.MouseClick(usbRadio);
                Thread.Sleep(600);
            }

            // ---- 5) Hedef klasor ----
            try { Directory.CreateDirectory(klasor); }
            catch (Exception ex) { Log.Yaz("HATA: Klasor olusturulamadi: " + ex.Message); return 5; }
            Log.Yaz("Kayit klasoru hazir: " + klasor);
            Yazdir("");
            Yazdir("-----------------------------------------------------");

            // ---- 6) Ana dongu ----
            var sonuclar = new List<OdaSonuc>();
            var bosSiralar = new List<int>();
            int ardisikBos = 0;
            int atlananSayisi = 0;
            string oncekiOda = null;
            SiraOdaYukle();

            for (int sira = ilk; sira <= son; sira++)
            {
                var s = new OdaSonuc { Sira = sira };
                string etiket = "[" + sira + "/" + son + "]";

                try
                {
                    // --- Bu siradaki oda bugun zaten alindiysa tekrar okuma ---
                    // Yarim kalan bir gunu tamamlarken 15 dakika yerine 1-2 dakika surer.
                    string bilinenOda;
                    if (!_tumunuOku && _siraOda.TryGetValue(sira, out bilinenOda))
                    {
                        string varOlan = Path.Combine(klasor, TemizAd(bilinenOda) + ".pdf");
                        if (File.Exists(varOlan) && new FileInfo(varOlan).Length >= KUCUK_PDF_SINIRI)
                        {
                            Console.WriteLine(etiket + " Sira " + sira + " -> Oda " + bilinenOda +
                                              " zaten alinmis, atlandi");
                            s.OdaNo = bilinenOda;
                            s.Basarili = true;
                            s.Boyut = new FileInfo(varOlan).Length;
                            oncekiOda = bilinenOda;
                            ardisikBos = 0;
                            atlananSayisi++;
                            sonuclar.Add(s);
                            continue;
                        }
                    }

                    ArtikDiyaloglariTemizle();

                    Console.Write(etiket + " Sira " + sira + " okunuyor...");

                    // -- okuma (gerekirse tekrar dene) --
                    string oda = null, okumaHata = null;
                    for (int deneme = 1; deneme <= 2; deneme++)
                    {
                        oda = TekOkuma(odaCombo, okuBtn, memo, sira, out okumaHata);

                        if (oda != null && oda == oncekiOda)
                        {
                            // ayni oda tekrar geldi: secim uygulanmamis olabilir
                            Log.Sadece(etiket + " ayni oda (" + oda + ") geldi, okuma tekrarlaniyor.");
                            okumaHata = "Ayni oda tekrar okundu (" + oda + ")";
                            oda = null;
                        }
                        if (oda != null) break;

                        ArtikDiyaloglariTemizle();
                        if (deneme == 1) Thread.Sleep(1200);
                    }

                    if (oda == null)
                    {
                        if (okumaHata != null && okumaHata.StartsWith(BOS_ISARET, StringComparison.Ordinal))
                        {
                            // Bu sirada terminalde kayit yok.
                            // ONEMLI: Kayitlar terminalde ARDISIK DEGIL - aradaki bir
                            // sira bos olsa da sonrakilerde veri olabiliyor. Bu yuzden
                            // durmuyoruz, atlayip devam ediyoruz.
                            Console.WriteLine("  BOS (atlandi)");
                            bosSiralar.Add(sira);
                            ardisikBos++;
                            Log.Sadece(etiket + " bos slot atlandi (" +
                                       okumaHata.Substring(BOS_ISARET.Length) + ")");

                            if (ardisikBos >= ARDISIK_BOS_SINIRI)
                            {
                                Log.Yaz("");
                                Log.Yaz(ARDISIK_BOS_SINIRI + " sira ust uste bos geldi -> " +
                                        "terminalde baska kayit yok, duruluyor.");
                                break;
                            }
                            continue;   // bos slot basarisizlik sayilmaz
                        }

                        s.Hata = okumaHata ?? "Okuma basarisiz";
                        Console.WriteLine("  BASARISIZ");
                        Log.Sadece(etiket + " " + s.Hata);
                        sonuclar.Add(s);
                        continue;
                    }
                    s.OdaNo = oda;
                    Console.Write(" Oda " + oda + " ...");

                    // -- PDF olustur --
                    string hedefDosya = Path.Combine(klasor, TemizAd(oda) + ".pdf");
                    string hata;
                    if (!PdfKaydet(yazdirBtn, hedefDosya, out hata))
                    {
                        s.Hata = hata;
                        Console.WriteLine("  PDF HATASI");
                        Log.Sadece(etiket + " PDF hatasi: " + hata);
                        sonuclar.Add(s);
                        OnizlemeyiKapat();
                        ArtikDiyaloglariTemizle();
                        continue;
                    }

                    var fi = new FileInfo(hedefDosya);

                    // Cok kucuk PDF = rapor kayitlar yuklenmeden uretilmis olabilir.
                    // Bir kez daha dene; yine kucukse odada gercekten az kayit var demektir.
                    if (fi.Length < KUCUK_PDF_SINIRI)
                    {
                        Log.Sadece(etiket + " PDF cok kucuk (" + fi.Length + " bayt), tekrar deneniyor.");
                        string h2;
                        if (PdfKaydet(yazdirBtn, hedefDosya, out h2))
                        {
                            fi = new FileInfo(hedefDosya);
                            if (fi.Length < KUCUK_PDF_SINIRI)
                                Log.Sadece(etiket + " ikinci denemede de kucuk (" + fi.Length + " bayt).");
                        }
                    }

                    s.Basarili = true;
                    s.Boyut = fi.Length;
                    oncekiOda = oda;
                    ardisikBos = 0;   // veri geldi, bos sayaci sifirlanir
                    _siraOda[sira] = oda;   // sira -> oda eslesmesini ogren
                    Console.WriteLine("  OK  (" + (fi.Length / 1024) + " KB)");
                    Log.Sadece(etiket + " OK oda=" + oda + " dosya=" + hedefDosya + " boyut=" + fi.Length);
                    sonuclar.Add(s);
                }
                catch (Exception ex)
                {
                    s.Hata = ex.Message;
                    Console.WriteLine("  HATA: " + ex.Message);
                    Log.Sadece(etiket + " istisna: " + ex);
                    sonuclar.Add(s);
                    OnizlemeyiKapat();
                    ArtikDiyaloglariTemizle();
                }
            }

            // ---- 7) Ozet ----
            Yazdir("-----------------------------------------------------");
            Yazdir("");
            int ok = 0, hatali = 0;
            foreach (var s in sonuclar) { if (s.Basarili) ok++; else hatali++; }

            SiraOdaKaydet();

            Log.Yaz("OZET: " + ok + " basarili, " + hatali + " basarisiz (toplam " + sonuclar.Count + ")");
            if (atlananSayisi > 0)
                Log.Yaz("      " + atlananSayisi + " oda zaten alinmisti, tekrar okunmadi");
            if (bosSiralar.Count > 0)
                Log.Yaz("      " + bosSiralar.Count + " sira bostu, atlandi: " +
                        string.Join(", ", bosSiralar.ConvertAll(x => x.ToString()).ToArray()));
            Log.Yaz("Klasor: " + klasor);
            Log.Yaz("Klasordeki toplam PDF: " + Directory.GetFiles(klasor, "*.pdf").Length);

            if (hatali > 0)
            {
                Yazdir("");
                Yazdir("Basarisiz olanlar:");
                foreach (var s in sonuclar)
                    if (!s.Basarili)
                        Log.Yaz("   Sira " + s.Sira + (s.OdaNo != null ? " (oda " + s.OdaNo + ")" : "") + " : " + s.Hata);
            }

            return hatali == 0 ? 0 : 10;
        }

        // =============================================================
        /// <summary>Verilen sira numarasini secip terminalden okur.
        /// Basarili olursa kilit bilgisinden okunan oda numarasini dondurur.</summary>
        static string TekOkuma(IntPtr odaCombo, IntPtr okuBtn, IntPtr memo, int sira, out string hata)
        {
            hata = null;
            IntPtr r;

            // ---- 1) oda sirasini sec ----
            Win32.Send(odaCombo, Win32.CB_SETCURSEL, new IntPtr(sira - 1), IntPtr.Zero);
            Thread.Sleep(80);

            // VCL'in OnChange olayini tetikle. Bildirim, combobox'in GERCEK ebeveynine
            // gitmeli - frame'e gonderilirse VCL mesaji ilgili kontrole yonlendiremez.
            IntPtr comboEbeveyn = Win32.GetParent(odaCombo);
            int comboId = Win32.GetDlgCtrlID(odaCombo);
            IntPtr wp = new IntPtr((1 << 16) | (comboId & 0xFFFF));   // CBN_SELCHANGE = 1
            Win32.PostMessage(comboEbeveyn, Win32.WM_COMMAND, wp, odaCombo);
            Thread.Sleep(180);

            int? seciliIdx = Win32.Send(odaCombo, Win32.CB_GETCURSEL, IntPtr.Zero, IntPtr.Zero);
            if (seciliIdx != sira - 1)
            {
                hata = "Oda sirasi secilemedi (istenen " + (sira - 1) + ", olan " + seciliIdx + ")";
                return null;
            }

            // ---- 2) kilit bilgisi kutusunu temizle ----
            // Boylece gelen verinin GERCEKTEN yeni oldugunu kesin anlayabiliriz.
            Win32.SendMessageTimeoutStr(memo, Win32.WM_SETTEXT, IntPtr.Zero, "",
                                        Win32.SMTO_ABORTIFHUNG, 3000, out r);
            Thread.Sleep(80);

            // ---- 3) Kayit oku ----
            Win32.MouseClick(okuBtn);

            // ---- 4) ilerleme penceresini izle ----
            var bas = DateTime.Now;
            bool ilerlemeGoruldu = false;
            while ((DateTime.Now - bas).TotalSeconds < 15)
            {
                if (PencereBulSinif(CLS_ILERLEME) != IntPtr.Zero) { ilerlemeGoruldu = true; break; }
                string ara = Win32.ControlText(memo);
                if (!string.IsNullOrEmpty(ara) && ara.Length > 50) break;   // cok hizli bitmis
                if (HataDiyalogu() != IntPtr.Zero)
                {
                    hata = CihazHatasi();
                    return null;
                }
                Thread.Sleep(50);
            }

            if (ilerlemeGoruldu)
            {
                while ((DateTime.Now - bas).TotalSeconds < 240)
                {
                    if (PencereBulSinif(CLS_ILERLEME) == IntPtr.Zero) break;
                    Thread.Sleep(80);
                }
                if (PencereBulSinif(CLS_ILERLEME) != IntPtr.Zero)
                {
                    hata = "Okuma 4 dakikada bitmedi";
                    return null;
                }
            }

            // ---- 5) kilit bilgisi dolana kadar bekle ----
            var bas2 = DateTime.Now;
            while ((DateTime.Now - bas2).TotalSeconds < 25)
            {
                string m = Win32.ControlText(memo);
                string ad = OdaAdiCikar(m);          // dosya adi icin GERCEK oda adi
                if (!string.IsNullOrEmpty(ad))
                {
                    string no = OdaNumarasiCikar(m);
                    if (no != null && no != ad) Log.Sadece("  Oda No=" + no + "  ->  Oda adi=" + ad);

                    // ONEMLI: Kilit bilgisi kutusu, kayit TABLOSUNDAN once dolabiliyor.
                    // Tablo dolmadan 'Yazdir'a basilirsa BOS rapor uretilir. Bu yuzden
                    // uygulamanin isini gercekten bitirmesini bekliyoruz.
                    UygulamaBostaBekle(20000);
                    return ad;
                }
                if (HataDiyalogu() != IntPtr.Zero)
                {
                    hata = CihazHatasi();
                    return null;
                }
                Thread.Sleep(100);
            }

            hata = ilerlemeGoruldu
                 ? "Okuma bitti ama kilit bilgisi gelmedi"
                 : "Okuma baslamadi (terminal yanit vermedi)";
            return null;
        }

        // =============================================================
        // Yazdir -> onizleme -> PDF export -> farkli kaydet -> dosya
        static bool PdfKaydet(IntPtr yazdirBtn, string hedefDosya, out string hata)
        {
            hata = null;

            try { if (File.Exists(hedefDosya)) File.Delete(hedefDosya); }
            catch (Exception ex) { hata = "Eski dosya silinemedi: " + ex.Message; return false; }

            // --- Yazdir ---
            // Ilk tiklama bazen yutuluyor. Kor bekleme yerine tiklamanin ISLEYIP
            // islemedigini olcuyoruz: onizleme acildi mi, ana pencere devre disi
            // kaldi mi, ya da uygulama mesgul mu (rapor uretiyorsa mesaja yanit vermez).
            // Islemediyse 300 ms icinde tekrar tikliyoruz - bos bekleme yok.
            IntPtr onizleme = IntPtr.Zero;
            for (int deneme = 1; deneme <= 8 && onizleme == IntPtr.Zero; deneme++)
            {
                Win32.MouseClick(yazdirBtn);

                bool isledi = false;
                var bk = DateTime.Now;
                while ((DateTime.Now - bk).TotalMilliseconds < 300)
                {
                    if (PencereBulSinif(CLS_ONIZLEME) != IntPtr.Zero) { isledi = true; break; }
                    if (!Win32.IsWindowEnabled(_ana)) { isledi = true; break; }
                    // WM_NULL yanit vermiyorsa uygulama rapor uretiyor demektir
                    if (Win32.Send(_ana, 0, IntPtr.Zero, IntPtr.Zero, 120) == null) { isledi = true; break; }
                    Thread.Sleep(20);
                }
                if (!isledi) { Log.Sadece("'Yazdir' tiklamasi islemedi, hemen tekrar."); continue; }

                onizleme = PencereBekle(CLS_ONIZLEME, 25);
            }
            if (onizleme == IntPtr.Zero) { hata = "Onizleme penceresi acilmadi"; return false; }

            // rapor uretimi bitene kadar bekle: pencere etkin olmali
            var basE = DateTime.Now;
            while ((DateTime.Now - basE).TotalSeconds < 60 && !Win32.IsWindowEnabled(onizleme))
                Thread.Sleep(40);

            // --- arac cubugu hazir olana kadar bekle ---
            IntPtr toolbar = IntPtr.Zero;
            int butonSayisi = 0;
            var basT = DateTime.Now;
            while ((DateTime.Now - basT).TotalSeconds < 30)
            {
                toolbar = IntPtr.Zero;
                foreach (var c in Win32.Children(onizleme))
                    if (Win32.ClassOf(c) == CLS_TOOLBAR) { toolbar = c; break; }
                if (toolbar != IntPtr.Zero)
                {
                    int? n = Win32.Send(toolbar, Win32.TB_BUTTONCOUNT, IntPtr.Zero, IntPtr.Zero);
                    if (n.HasValue && n.Value > PDF_BUTON_INDEX) { butonSayisi = n.Value; break; }
                }
                Thread.Sleep(40);
            }
            if (toolbar == IntPtr.Zero || butonSayisi == 0)
            { hata = "Onizleme arac cubugu hazir olmadi"; return false; }

            int bx, by;
            if (!ToolbarButonMerkezi(toolbar, PDF_BUTON_INDEX, out bx, out by))
            { hata = "PDF butonunun konumu belirlenemedi"; return false; }

            // --- PDF butonuna bas. Ilk tiklama cogu zaman sadece pencereyi
            //     etkinlestirdigi icin kisa araliklarla hizlica tekrar deniyoruz. ---
            IntPtr expDlg = IntPtr.Zero;
            for (int deneme = 1; deneme <= 10 && expDlg == IntPtr.Zero; deneme++)
            {
                Win32.MouseClick(toolbar, bx, by);
                expDlg = PencereBekle(CLS_EXPORT, deneme <= 4 ? 0.45 : 5);
            }
            if (expDlg == IntPtr.Zero) { hata = "PDF disa aktarma penceresi acilmadi"; return false; }

            // --- export ayarlari ---
            IntPtr okBtn = IntPtr.Zero;
            foreach (var c in Win32.Children(expDlg))
            {
                string k = Win32.ClassOf(c);
                string t = Win32.TitleOf(c);

                if (k == "TCheckBox" && t == "Open after export")
                {
                    if (Win32.Send(c, Win32.BM_GETCHECK, IntPtr.Zero, IntPtr.Zero) == 1)
                    { Win32.PostMessage(c, Win32.BM_CLICK, IntPtr.Zero, IntPtr.Zero); Thread.Sleep(120); }
                }
                else if (k == "TRadioButton" && t == "All")
                {
                    if (Win32.Send(c, Win32.BM_GETCHECK, IntPtr.Zero, IntPtr.Zero) != 1)
                    { Win32.PostMessage(c, Win32.BM_CLICK, IntPtr.Zero, IntPtr.Zero); Thread.Sleep(120); }
                }
                else if (k == "TButton" && t == "OK") okBtn = c;
            }
            if (okBtn == IntPtr.Zero) { hata = "Export penceresinde OK butonu yok"; return false; }

            Win32.PostMessage(okBtn, Win32.BM_CLICK, IntPtr.Zero, IntPtr.Zero);

            // --- Farkli Kaydet diyalogu ---
            IntPtr kaydet = KaydetDiyaloguBekle(30);
            if (kaydet == IntPtr.Zero) { hata = "'Farkli Kaydet' penceresi acilmadi"; return false; }

            IntPtr edit = IntPtr.Zero, saveBtn = IntPtr.Zero;
            foreach (var c in Win32.Children(kaydet))
            {
                if (edit == IntPtr.Zero && Win32.ClassOf(c) == "Edit" && Win32.GetDlgCtrlID(c) == 1001) edit = c;
                if (saveBtn == IntPtr.Zero && Win32.ClassOf(c) == "Button" && Win32.GetDlgCtrlID(c) == 1) saveBtn = c;
            }
            if (edit == IntPtr.Zero || saveBtn == IntPtr.Zero)
            { hata = "Kaydetme penceresinin alanlari bulunamadi"; return false; }

            // --- dosya adini GERCEK tus girisi ile yaz ---
            // (WM_SETTEXT yeterli degil: kabuk diyalogu kendi ic durumunu kullanir)
            if (!DosyaAdiYaz(edit, hedefDosya))
            { hata = "Dosya adi yazilamadi"; return false; }

            Win32.PostMessage(saveBtn, Win32.BM_CLICK, IntPtr.Zero, IntPtr.Zero);

            // --- Dosyayi beklerken ayni anda "uzerine yaz?" onayini da yakala.
            //     (Ayri ayri beklemek bos yere saniyeler kaybettiriyordu.) ---
            if (!DosyaBekleVeOnayla(hedefDosya, 90))
            { hata = "PDF dosyasi olusmadi: " + hedefDosya; OnizlemeyiKapat(); return false; }

            OnizlemeyiKapat();
            return true;
        }

        /// <summary>Kabuk 'Farkli Kaydet' diyalogundaki dosya adi alanina gercek karakter
        /// girisi yapar ve dogrular.</summary>
        static bool DosyaAdiYaz(IntPtr edit, string tamYol)
        {
            for (int deneme = 1; deneme <= 3; deneme++)
            {
                Win32.Send(edit, Win32.EM_SETSEL, IntPtr.Zero, new IntPtr(-1));   // tumunu sec
                Thread.Sleep(50);
                foreach (char ch in tamYol)
                    Win32.PostMessage(edit, Win32.WM_CHAR, new IntPtr((int)ch), new IntPtr(1));

                // yazilan metnin islenmesini kisa araliklarla dogrula
                for (int i = 0; i < 40; i++)
                {
                    Thread.Sleep(25);
                    string k = Win32.ControlText(edit);
                    if (k != null && k.Equals(tamYol, StringComparison.OrdinalIgnoreCase)) return true;
                }

                Log.Sadece("Dosya adi yazma denemesi " + deneme + " basarisiz. Okunan: '" +
                           Win32.ControlText(edit) + "'");
                Thread.Sleep(200);
            }
            return false;
        }

        /// <summary>Arac cubugundaki butonun istemci koordinatlarindaki merkezini bulur.
        /// Surecler arasi TB_GETITEMRECT icin hedef surecte bellek ayirir.</summary>
        static bool ToolbarButonMerkezi(IntPtr toolbar, int index, out int cx, out int cy)
        {
            cx = 0; cy = 0;
            const uint PROCESS_HAKLARI = 0x0438;   // VM_OPERATION|VM_READ|VM_WRITE|QUERY_INFORMATION
            IntPtr hProc = Win32.OpenProcess(PROCESS_HAKLARI, false, _pid);
            if (hProc == IntPtr.Zero) return false;

            IntPtr uzak = IntPtr.Zero;
            try
            {
                int? adet = Win32.Send(toolbar, Win32.TB_BUTTONCOUNT, IntPtr.Zero, IntPtr.Zero);
                if (!adet.HasValue || index >= adet.Value) return false;

                uzak = Win32.VirtualAllocEx(hProc, IntPtr.Zero, new IntPtr(256), 0x3000, 0x04);
                if (uzak == IntPtr.Zero) return false;

                if (Win32.Send(toolbar, Win32.TB_GETITEMRECT, new IntPtr(index), uzak) == null) return false;

                var buf = new byte[16];
                IntPtr okunan;
                if (!Win32.ReadProcessMemory(hProc, uzak, buf, 16, out okunan)) return false;

                int l = BitConverter.ToInt32(buf, 0);
                int t = BitConverter.ToInt32(buf, 4);
                int r = BitConverter.ToInt32(buf, 8);
                int b = BitConverter.ToInt32(buf, 12);
                if (r <= l || b <= t) return false;

                cx = (l + r) / 2;
                cy = (t + b) / 2;
                return true;
            }
            finally
            {
                if (uzak != IntPtr.Zero) Win32.VirtualFreeEx(hProc, uzak, IntPtr.Zero, 0x8000);
                Win32.CloseHandle(hProc);
            }
        }

        // =============================================================
        // Pencere yardimcilari

        static IntPtr Bul(List<IntPtr> liste, Func<IntPtr, bool> kosul)
        {
            foreach (var h in liste) if (kosul(h)) return h;
            return IntPtr.Zero;
        }

        /// <summary>Bir metin kutusunu kesin olarak temizleyip verilen metni yazar.
        /// Once WM_SETTEXT ile bosaltir (secim durumundan bagimsiz), sonra gercek
        /// tus girisi gonderir - VCL bilesenleri metni bu yolla guvenilir alir.</summary>
        static void AlaniDoldur(IntPtr kutu, string metin)
        {
            IntPtr r;
            Win32.SendMessageTimeoutStr(kutu, Win32.WM_SETTEXT, IntPtr.Zero, "",
                                        Win32.SMTO_ABORTIFHUNG, 3000, out r);
            Thread.Sleep(120);
            Win32.Send(kutu, Win32.EM_SETSEL, IntPtr.Zero, new IntPtr(-1));
            Thread.Sleep(60);
            foreach (char ch in metin)
            {
                Win32.PostMessage(kutu, Win32.WM_CHAR, new IntPtr((int)ch), new IntPtr(1));
                Thread.Sleep(12);
            }
        }

        /// <summary>Sira -> oda eslesmesini diskten okur (varsa).</summary>
        static void SiraOdaYukle()
        {
            _siraOda.Clear();
            try
            {
                if (!File.Exists(SIRA_ODA_DOSYA)) return;
                foreach (var satir in File.ReadAllLines(SIRA_ODA_DOSYA, Encoding.UTF8))
                {
                    string s = satir.Trim();
                    if (s.Length == 0 || s.StartsWith("#")) continue;
                    int e = s.IndexOf('=');
                    if (e <= 0) continue;
                    int sira;
                    if (!int.TryParse(s.Substring(0, e).Trim(), out sira)) continue;
                    string oda = s.Substring(e + 1).Trim();
                    if (oda.Length > 0) _siraOda[sira] = oda;
                }
                Log.Sadece("Sira-oda eslesmesi yuklendi: " + _siraOda.Count + " kayit");
            }
            catch (Exception ex) { Log.Sadece("Sira-oda dosyasi okunamadi: " + ex.Message); }
        }

        /// <summary>Sira -> oda eslesmesini diske yazar.</summary>
        static void SiraOdaKaydet()
        {
            try
            {
                var satirlar = new List<string>
                {
                    "# El terminalindeki sira numarasi -> oda adi eslesmesi.",
                    "# Yarim kalan bir gunu tamamlarken alinmis odalari atlamak icin kullanilir.",
                    "# Otomatik uretilir; elle duzenlemeniz gerekmez.",
                    ""
                };
                var anahtarlar = new List<int>(_siraOda.Keys);
                anahtarlar.Sort();
                foreach (var k in anahtarlar) satirlar.Add(k + "=" + _siraOda[k]);
                File.WriteAllLines(SIRA_ODA_DOSYA, satirlar.ToArray(), new UTF8Encoding(true));
            }
            catch (Exception ex) { Log.Sadece("Sira-oda dosyasi yazilamadi: " + ex.Message); }
        }

        /// <summary>Ana pencereyi bulur (gizli olsa bile). Yoksa IntPtr.Zero.</summary>
        static IntPtr AnaPencereBul()
        {
            foreach (var h in Win32.TumUstPencereler(_pid))
                if (Win32.ClassOf(h) == CLS_ANA) return h;
            return IntPtr.Zero;
        }

        /// <summary>Kale Kilit giris ekranini otomatik doldurup oturum acar.</summary>
        static bool OtomatikGiris(out string hata)
        {
            hata = null;

            // ---- giris formunu bul, gorunur degilse gorunur olmasini bekle ----
            IntPtr giris = IntPtr.Zero;
            for (int i = 0; i < 80; i++)          // en fazla ~24 sn
            {
                giris = IntPtr.Zero;
                foreach (var h in Win32.TumUstPencereler(_pid))
                    if (Win32.ClassOf(h) == CLS_GIRIS) { giris = h; break; }

                if (giris != IntPtr.Zero && Win32.IsWindowVisible(giris)) break;

                // ana ekran kendiliginden acildiysa giris gerekmiyor
                foreach (var h in Win32.TumUstPencereler(_pid))
                    if (Win32.ClassOf(h) == CLS_ANA && Win32.IsWindowVisible(h)) return true;

                Thread.Sleep(300);
            }
            if (giris == IntPtr.Zero) { hata = "Giris formu bulunamadi"; return false; }
            if (!Win32.IsWindowVisible(giris))
            {
                Win32.ShowWindow(giris, Win32.SW_SHOW);
                Thread.Sleep(500);
            }

            // ---- alanlari tani ----
            // Sifre  : etkin olan TRzEdit
            // Kullanici: icinde Edit olan TRzComboBox (duzenlenebilir acilir liste)
            IntPtr sifreKutusu = IntPtr.Zero, kullaniciKutusu = IntPtr.Zero, girisBtn = IntPtr.Zero;

            var cocuklar = Win32.Children(giris);
            foreach (var c in cocuklar)
            {
                string k = Win32.ClassOf(c);
                string t = Win32.TitleOf(c);

                if (k == "TRzBitBtn" && t.StartsWith("Gir", StringComparison.Ordinal))
                    girisBtn = c;
                else if (k == "TRzEdit" && Win32.IsWindowEnabled(c) && sifreKutusu == IntPtr.Zero)
                    sifreKutusu = c;
                else if (k == "TRzComboBox" && kullaniciKutusu == IntPtr.Zero)
                {
                    foreach (var ic in Win32.Children(c))
                        if (Win32.ClassOf(ic) == "Edit") { kullaniciKutusu = c; break; }
                }
            }

            Log.Sadece("Giris formu: kullanici=" + kullaniciKutusu +
                       " sifre=" + sifreKutusu + " buton=" + girisBtn);

            if (girisBtn == IntPtr.Zero) { hata = "'Giris' butonu bulunamadi"; return false; }
            if (sifreKutusu == IntPtr.Zero) { hata = "Sifre alani bulunamadi"; return false; }

            // ---- operator (kullanici) ----
            // DIKKAT: bu bir acilir liste. Metnini silip yeniden yazmak listedeki
            // secimi (ItemIndex) bozar ve uygulama operatoru bos sayip
            // "sifre yanlis" der. Bu yuzden metne DOKUNMUYORUZ; gerekiyorsa
            // dogru ogeyi listeden seciyoruz.
            if (kullaniciKutusu != IntPtr.Zero)
            {
                string mevcutKullanici = Win32.ControlText(kullaniciKutusu) ?? "";
                if (mevcutKullanici.Equals(_kullanici, StringComparison.OrdinalIgnoreCase))
                {
                    Log.Sadece("Operator zaten dogru: " + mevcutKullanici);
                }
                else
                {
                    int adet = Win32.Send(kullaniciKutusu, Win32.CB_GETCOUNT,
                                          IntPtr.Zero, IntPtr.Zero) ?? 0;
                    int bulunan = -1;
                    for (int i = 0; i < adet; i++)
                    {
                        var sb = new StringBuilder(256);
                        IntPtr rr;
                        Win32.SendMessageTimeoutSB(kullaniciKutusu, Win32.CB_GETLBTEXT,
                                                   new IntPtr(i), sb,
                                                   Win32.SMTO_ABORTIFHUNG, 3000, out rr);
                        if (sb.ToString().Trim().Equals(_kullanici, StringComparison.OrdinalIgnoreCase))
                        { bulunan = i; break; }
                    }
                    if (bulunan < 0)
                    {
                        hata = "'" + _kullanici + "' operator listesinde yok";
                        return false;
                    }

                    Win32.Send(kullaniciKutusu, Win32.CB_SETCURSEL, new IntPtr(bulunan), IntPtr.Zero);
                    IntPtr ebeveyn = Win32.GetParent(kullaniciKutusu);
                    int kimlik = Win32.GetDlgCtrlID(kullaniciKutusu);
                    Win32.PostMessage(ebeveyn, Win32.WM_COMMAND,
                                      new IntPtr((1 << 16) | (kimlik & 0xFFFF)), kullaniciKutusu);
                    Thread.Sleep(350);
                    Log.Sadece("Operator listeden secildi: " + _kullanici + " (sira " + bulunan + ")");
                }
            }

            // ---- Sifreyi yaz ve giris yap ----
            // Sifre kutusuna yazma ara sira tutmuyor (odak gitmemis olabiliyor) ve
            // uygulama "sifre yanlis" diyor. Gunlukler bunun gecici oldugunu, ayni
            // sifreyle tekrar denendiginde basarili oldugunu gosteriyor. Bu yuzden
            // SADECE butona degil, TUM dongue (yaz + gonder) bastan tekrarlanir.
            string sonRed = null;

            for (int tur = 1; tur <= 4; tur++)
            {
                // operator secimi bozulmus olabilir - her turda dogrula
                if (kullaniciKutusu != IntPtr.Zero)
                {
                    string simdiki = Win32.ControlText(kullaniciKutusu) ?? "";
                    if (!simdiki.Equals(_kullanici, StringComparison.OrdinalIgnoreCase))
                        Log.Sadece("Tur " + tur + ": operator '" + simdiki + "' gorunuyor (beklenen " + _kullanici + ")");
                }

                // sifre alanina ONCE odaklan, sonra yaz
                Win32.MouseClick(sifreKutusu);
                Thread.Sleep(200);
                AlaniDoldur(sifreKutusu, _sifre);
                Thread.Sleep(350);

                Win32.MouseClick(girisBtn);

                bool anaEkranAcildi = false;
                string redMesaji = null;

                for (int i = 0; i < 70; i++)      // ~10 sn bekle
                {
                    foreach (var h in Win32.TumUstPencereler(_pid))
                        if (Win32.ClassOf(h) == CLS_ANA && Win32.IsWindowVisible(h))
                        { anaEkranAcildi = true; break; }
                    if (anaEkranAcildi) break;

                    IntPtr uyari = HataDiyalogu();
                    if (uyari != IntPtr.Zero)
                    {
                        redMesaji = Kisalt(DiyalogMetni(uyari));
                        ArtikDiyaloglariTemizle();
                        break;
                    }
                    Thread.Sleep(150);
                }

                if (anaEkranAcildi)
                {
                    if (tur > 1) Log.Sadece("Giris " + tur + ". turda basarili oldu.");
                    Thread.Sleep(1200);          // ana ekranin yerlesmesi icin
                    return true;
                }

                if (redMesaji != null)
                {
                    sonRed = redMesaji;
                    Log.Sadece("Giris turu " + tur + " reddedildi: " + redMesaji + " - tekrar deneniyor.");
                }
                else
                {
                    Log.Sadece("Giris turu " + tur + " yanitsiz kaldi - tekrar deneniyor.");
                }
                Thread.Sleep(900);
            }

            hata = sonRed != null
                 ? "Giris reddedildi (4 deneme): " + sonRed
                 : "Giris butonuna basildi ama ana ekran acilmadi";
            return false;
        }

        /// <summary>"Kilit acilis kayitlari" ekraninin frame'ini bulur.</summary>
        static IntPtr FrameBul()
        {
            foreach (var c in Win32.Children(_ana))
                if (Win32.ClassOf(c) == CLS_FRAME) return c;
            return IntPtr.Zero;
        }

        /// <summary>Sol menuden "Kayit arama -> Kilit acilis kayitlari" ekranini acar.
        /// Once klavye ile, olmazsa koordinatla dener; her adimda dogrulama yapar.</summary>
        static bool EkranaGit(out string hata)
        {
            hata = null;

            IntPtr solMenu = IntPtr.Zero;
            foreach (var c in Win32.Children(_ana))
                if (Win32.ClassOf(c) == "TRzToolbar") { solMenu = c; break; }
            if (solMenu == IntPtr.Zero) { hata = "Sol menu (TRzToolbar) bulunamadi"; return false; }

            var oncekiler = new List<IntPtr>(Win32.TopWindows(_pid));

            int menuY = MENU_ILK_Y + MENU_ARALIK * MENU_KAYIT_ARAMA;
            Log.Sadece("Sol menu 'Kayit arama' tiklaniyor: client(" + MENU_X + "," + menuY + ")");
            Win32.MouseClick(solMenu, MENU_X, menuY);
            Thread.Sleep(1400);

            if (FrameBul() != IntPtr.Zero) return true;   // alt menusuz dogrudan acildi

            // --- acilan alt menu penceresini bul ---
            // DIKKAT: Menu ile birlikte bir de "SysShadow" (golge) penceresi acilir ve
            // menunun uzerinde durur. Golgeye tiklamak HICBIR SEY yapmaz, bu yuzden
            // gercek menu sinifini (#32768) oncelikli sececegiz.
            IntPtr popup = IntPtr.Zero;
            Win32.RECT pr = new Win32.RECT();
            IntPtr yedekPopup = IntPtr.Zero;
            Win32.RECT yedekPr = new Win32.RECT();

            foreach (var h in Win32.TopWindows(_pid))
            {
                if (oncekiler.Contains(h)) continue;
                Win32.RECT r;
                Win32.GetWindowRect(h, out r);
                string sinif = Win32.ClassOf(h);
                Log.Sadece("Alt menu adayi: cls=" + sinif +
                           " rect=" + r.Left + "," + r.Top + "," + r.Right + "," + r.Bottom);

                if ((r.Right - r.Left) <= 40 || (r.Bottom - r.Top) <= 40) continue;
                if (sinif == "SysShadow") continue;              // golge penceresi - ise yaramaz

                if (sinif == "#32768") { popup = h; pr = r; }    // gercek menu
                else if (yedekPopup == IntPtr.Zero) { yedekPopup = h; yedekPr = r; }
            }
            if (popup == IntPtr.Zero && yedekPopup != IntPtr.Zero) { popup = yedekPopup; pr = yedekPr; }
            if (popup == IntPtr.Zero) { hata = "Alt menu acilmadi"; return false; }
            Log.Sadece("Alt menu secildi: " + popup + " (" + Win32.ClassOf(popup) + ")");

            // --- 1) Menunun KENDI yapisini oku ve ogenin tam yerini bul ---
            // Acilir menuler kendi modal giris dongusunu calistirdigi icin gonderilen
            // mesajlari (PostMessage) GORMEZ. Bu yuzden ogenin ekrandaki gercek
            // dikdortgenini alip oraya GERCEK fare tiklamasi yapiyoruz.
            IntPtr hMenu = IntPtr.Zero;
            int? hm = Win32.Send(popup, Win32.MN_GETHMENU, IntPtr.Zero, IntPtr.Zero, 3000);
            if (hm.HasValue && hm.Value != 0) hMenu = new IntPtr(hm.Value);

            if (hMenu != IntPtr.Zero)
            {
                int adet = Win32.GetMenuItemCount(hMenu);
                Log.Sadece("Menu yapisi okundu: " + adet + " oge");

                int hedefIndex = -1;
                for (int i = 0; i < adet; i++)
                {
                    var sb = new StringBuilder(260);
                    Win32.GetMenuString(hMenu, i, sb, sb.Capacity, Win32.MF_BYPOSITION);
                    string metin = sb.ToString();
                    Log.Sadece("   oge[" + i + "] = '" + metin + "'");

                    // "Kilit açılış kayıtları" -> "Kilit" ile baslar ve "kay" icerir.
                    // "Kilit bilgisi" ile karismamasi icin ikisi birden aranir.
                    if (metin.StartsWith("Kilit", StringComparison.OrdinalIgnoreCase) &&
                        metin.IndexOf("kay", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        hedefIndex = i;
                    }
                }
                if (hedefIndex < 0 && adet > ALTMENU_KILIT_ACILIS)
                    hedefIndex = ALTMENU_KILIT_ACILIS;      // metin okunamadiysa sabit sira

                if (hedefIndex >= 0)
                {
                    Win32.RECT ogeR;
                    bool oldu = Win32.GetMenuItemRect(popup, hMenu, hedefIndex, out ogeR);
                    if (!oldu) oldu = Win32.GetMenuItemRect(IntPtr.Zero, hMenu, hedefIndex, out ogeR);

                    if (oldu && ogeR.Right > ogeR.Left)
                    {
                        int ex = (ogeR.Left + ogeR.Right) / 2;
                        int ey = (ogeR.Top + ogeR.Bottom) / 2;
                        Log.Sadece("Oge[" + hedefIndex + "] ekran rect=" + ogeR.Left + "," + ogeR.Top +
                                   "," + ogeR.Right + "," + ogeR.Bottom + " -> tiklanacak nokta " + ex + "," + ey);
                        Win32.GercekTikla(ex, ey);
                        if (FrameGelmesiniBekle(6))
                        { Log.Sadece("Alt menu ogesi secildi (menu yapisindan)."); return true; }
                    }
                    else Log.Sadece("GetMenuItemRect basarisiz.");
                }
            }
            else Log.Sadece("MN_GETHMENU sonuc vermedi.");

            // --- 2) Yedek: pencere dikdortgeninden hesaplayip gercek tiklama ---
            int yukseklik = pr.Bottom - pr.Top;
            int kenar = 3;
            double ogeYuksekligi = (double)(yukseklik - 2 * kenar) / ALTMENU_OGE_SAYISI;
            int yx = (pr.Left + pr.Right) / 2;
            int yy = (int)(pr.Top + kenar + ogeYuksekligi * (ALTMENU_KILIT_ACILIS + 0.5));
            Log.Sadece("Yedek yontem: ekran noktasi " + yx + "," + yy +
                       "  ogeYuksekligi=" + ogeYuksekligi.ToString("0.0"));
            Win32.GercekTikla(yx, yy);
            if (FrameGelmesiniBekle(6)) { Log.Sadece("Alt menu yedek yontemle secildi."); return true; }

            // --- basarisiz: menuyu kapat ---
            Win32.PostMessage(popup, 0x0100, new IntPtr(0x1B), IntPtr.Zero);       // VK_ESCAPE
            Win32.PostMessage(popup, 0x0101, new IntPtr(0x1B), IntPtr.Zero);
            Thread.Sleep(500);
            hata = "Alt menuden 'Kilit acilis kayitlari' secilemedi";
            return false;
        }

        /// <summary>Bos slot bildiren cihaz hatalarinin basina konan isaret.</summary>
        const string BOS_ISARET = "BOS:";

        /// <summary>Acik cihaz hata penceresini okur, metnini dondurur.
        /// Slotta veri olmadigini bildiren hatalari BOS: ile isaretler.</summary>
        static string CihazHatasi()
        {
            IntPtr d = HataDiyalogu();
            string mesaj = d != IntPtr.Zero ? Kisalt(DiyalogMetni(d)) : "bilinmeyen hata";

            // "17:Kart veri formatı hatası!" -> slotta gecerli kayit yok
            bool bos = mesaj.IndexOf("17:", StringComparison.Ordinal) >= 0 ||
                       mesaj.IndexOf("format", StringComparison.OrdinalIgnoreCase) >= 0;

            return (bos ? BOS_ISARET : "") + "Cihaz hata verdi: " + mesaj;
        }

        /// <summary>Uygulamanin isini bitirmesini bekler. Kayit tablosu dolarken
        /// uygulama mesajlara gec yanit verir; ust uste birkac kez hizli yanit
        /// alinca islem bitmis demektir.</summary>
        static void UygulamaBostaBekle(int azamiMs)
        {
            var bas = DateTime.Now;
            int ardisikBosta = 0;
            while ((DateTime.Now - bas).TotalMilliseconds < azamiMs)
            {
                bool ilerlemeVar = PencereBulSinif(CLS_ILERLEME) != IntPtr.Zero;
                bool yanitVeriyor = Win32.Send(_ana, 0, IntPtr.Zero, IntPtr.Zero, 150) != null;

                if (!ilerlemeVar && yanitVeriyor)
                {
                    if (++ardisikBosta >= 3) return;
                }
                else ardisikBosta = 0;

                Thread.Sleep(110);
            }
            Log.Sadece("Uygulama " + azamiMs + " ms icinde bosa dusmedi, devam ediliyor.");
        }

        static bool FrameGelmesiniBekle(int saniye)
        {
            var bas = DateTime.Now;
            while ((DateTime.Now - bas).TotalSeconds < saniye)
            {
                if (FrameBul() != IntPtr.Zero) { Thread.Sleep(800); return true; }
                Thread.Sleep(250);
            }
            return false;
        }

        static IntPtr PencereBulSinif(string sinif)
        {
            foreach (var h in Win32.TopWindows(_pid))
                if (Win32.ClassOf(h) == sinif) return h;
            return IntPtr.Zero;
        }

        static IntPtr PencereBekle(string sinif, double saniye)
        {
            var bas = DateTime.Now;
            while ((DateTime.Now - bas).TotalSeconds < saniye)
            {
                IntPtr h = PencereBulSinif(sinif);
                if (h != IntPtr.Zero) return h;
                Thread.Sleep(30);
            }
            return IntPtr.Zero;
        }

        /// <summary>Icinde 1001 numarali Edit ve 1 numarali Button olan #32770 diyalogunu bulur.</summary>
        static IntPtr KaydetDiyaloguBekle(int saniye)
        {
            var bas = DateTime.Now;
            while ((DateTime.Now - bas).TotalSeconds < saniye)
            {
                foreach (var h in Win32.TopWindows(_pid))
                {
                    if (Win32.ClassOf(h) != CLS_DIYALOG) continue;
                    bool editVar = false, btnVar = false;
                    foreach (var c in Win32.Children(h))
                    {
                        if (Win32.ClassOf(c) == "Edit" && Win32.GetDlgCtrlID(c) == 1001) editVar = true;
                        if (Win32.ClassOf(c) == "Button" && Win32.GetDlgCtrlID(c) == 1) btnVar = true;
                    }
                    if (editVar && btnVar) return h;
                }
                Thread.Sleep(30);
            }
            return IntPtr.Zero;
        }

        /// <summary>Hata mesaji penceresi (Static metinli #32770) varsa dondurur.</summary>
        static IntPtr HataDiyalogu()
        {
            foreach (var h in Win32.TopWindows(_pid))
            {
                if (Win32.ClassOf(h) != CLS_DIYALOG) continue;
                bool editVar = false;
                foreach (var c in Win32.Children(h))
                    if (Win32.ClassOf(c) == "Edit" && Win32.GetDlgCtrlID(c) == 1001) editVar = true;
                if (!editVar) return h;    // dosya diyalogu degil -> mesaj kutusu
            }
            return IntPtr.Zero;
        }

        /// <summary>Ekranda kalan hata/mesaj kutularini kapatir.</summary>
        static void ArtikDiyaloglariTemizle()
        {
            for (int i = 0; i < 8; i++)
            {
                IntPtr d = HataDiyalogu();
                if (d == IntPtr.Zero) return;
                string mesaj = DiyalogMetni(d);
                Log.Sadece("Artik diyalog kapatiliyor: " + Kisalt(mesaj));
                Win32.PostMessage(d, Win32.WM_COMMAND, new IntPtr(1), IntPtr.Zero);   // IDOK
                Win32.PostMessage(d, Win32.WM_COMMAND, new IntPtr(2), IntPtr.Zero);   // IDCANCEL
                Win32.PostMessage(d, Win32.WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
                Thread.Sleep(700);
            }
        }

        static string DiyalogMetni(IntPtr d)
        {
            var sb = new StringBuilder();
            foreach (var c in Win32.Children(d))
                if (Win32.ClassOf(c) == "Static")
                {
                    string t = Win32.TitleOf(c);
                    if (!string.IsNullOrEmpty(t)) sb.Append(t).Append(" ");
                }
            return sb.ToString().Trim();
        }

        static void OnizlemeyiKapat()
        {
            for (int i = 0; i < 15; i++)
            {
                IntPtr h = PencereBulSinif(CLS_ONIZLEME);
                if (h == IntPtr.Zero) break;
                Win32.PostMessage(h, Win32.WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
                // kapanmasini kisa araliklarla izle
                for (int j = 0; j < 25 && PencereBulSinif(CLS_ONIZLEME) != IntPtr.Zero; j++)
                    Thread.Sleep(40);
            }
            // ana pencere tekrar etkin olana kadar bekle
            for (int i = 0; i < 150; i++)
            {
                if (Win32.IsWindowEnabled(_ana)) return;
                Thread.Sleep(40);
            }
        }

        /// <summary>Dosyanin olusup yazilmasinin bitmesini bekler; bu sirada cikabilecek
        /// "uzerine yazilsin mi?" onayini da yanitlar. Dosya kilitten cikinca hemen doner.</summary>
        static bool DosyaBekleVeOnayla(string yol, int saniye)
        {
            var bas = DateTime.Now;
            bool onayVerildi = false;

            while ((DateTime.Now - bas).TotalSeconds < saniye)
            {
                if (File.Exists(yol))
                {
                    try
                    {
                        var fi = new FileInfo(yol);
                        if (fi.Length > 0)
                        {
                            // Ozel erisimle acilabiliyorsa yazma islemi bitmistir.
                            using (File.Open(yol, FileMode.Open, FileAccess.Read, FileShare.None)) { }
                            return true;
                        }
                    }
                    catch (IOException) { /* hala yaziliyor */ }
                    catch { }
                }
                else if (!onayVerildi)
                {
                    // dosya henuz yoksa uzerine yazma / uyari penceresi cikmis olabilir
                    if (OnayPenceresiniYanitla()) onayVerildi = true;
                }
                Thread.Sleep(40);
            }
            return File.Exists(yol) && new FileInfo(yol).Length > 0;
        }

        /// <summary>Ekranda "Evet" (IDYES) butonlu bir onay penceresi varsa onaylar.</summary>
        static bool OnayPenceresiniYanitla()
        {
            foreach (var h in Win32.TopWindows(_pid))
            {
                if (Win32.ClassOf(h) != CLS_DIYALOG) continue;
                foreach (var c in Win32.Children(h))
                {
                    if (Win32.ClassOf(c) == "Button" && Win32.GetDlgCtrlID(c) == 6)   // IDYES
                    {
                        Log.Sadece("Uzerine yazma onayi -> Evet");
                        Win32.PostMessage(h, Win32.WM_COMMAND, new IntPtr(6), IntPtr.Zero);
                        return true;
                    }
                }
            }
            return false;
        }

        // =============================================================

        // "Oda No:242"  -> teknik kilit numarasi (gunluk icin)
        static readonly Regex _odaNoRegex =
            new Regex(@"Oda\s*No\s*:\s*(\S+)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

        // "Oda adı:336" -> otelde kullanilan GERCEK oda adi; dosya adi BUNDAN uretilir.
        // 'adı' icindeki Turkce karakter kodlama sorunu yasatmasin diye \S* kullaniyoruz.
        static readonly Regex _odaAdiRegex =
            new Regex(@"Oda\s*ad\S*\s*:\s*(\S+)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

        /// <summary>Kilit bilgisinden dosya adinda kullanilacak oda adini cikarir.</summary>
        static string OdaAdiCikar(string memo)
        {
            if (string.IsNullOrEmpty(memo)) return null;
            var m = _odaAdiRegex.Match(memo);
            return m.Success ? m.Groups[1].Value.Trim() : null;
        }

        static string OdaNumarasiCikar(string memo)
        {
            if (string.IsNullOrEmpty(memo)) return null;
            var m = _odaNoRegex.Match(memo);
            return m.Success ? m.Groups[1].Value.Trim() : null;
        }

        static string TemizAd(string s)
        {
            var sb = new StringBuilder();
            foreach (char c in s)
                if (Array.IndexOf(Path.GetInvalidFileNameChars(), c) < 0) sb.Append(c);
            string r = sb.ToString().Trim();
            return r.Length == 0 ? "bilinmeyen" : r;
        }

        static string Kisalt(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Replace("\r", " ").Replace("\n", " ");
            return s.Length <= 160 ? s : s.Substring(0, 160) + "...";
        }
    }
}
