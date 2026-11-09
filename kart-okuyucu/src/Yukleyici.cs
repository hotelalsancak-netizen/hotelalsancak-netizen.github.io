// Yukleyici - gunun kayit klasorunu zipleyip GitHub veya GitLab'a yukler.
//
// Kimlik dogrulama jetonu (token) DUZ METIN olarak saklanmaz:
// Windows DPAPI ile SADECE bu kullanici hesabinin cozebilecegi sekilde sifrelenir.

using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace OdaKartOku
{
    #region Ayarlar

    /// <summary>Basit anahtar=deger ayar dosyasi.</summary>
    internal class Ayarlar
    {
        private readonly Dictionary<string, string> _d =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public string Dosya { get; private set; }

        public static Ayarlar Yukle(string dosya)
        {
            var a = new Ayarlar { Dosya = dosya };
            if (File.Exists(dosya))
            {
                foreach (var satir in File.ReadAllLines(dosya, Encoding.UTF8))
                {
                    string s = satir.Trim();
                    if (s.Length == 0 || s.StartsWith("#") || s.StartsWith(";")) continue;
                    int e = s.IndexOf('=');
                    if (e <= 0) continue;
                    a._d[s.Substring(0, e).Trim()] = s.Substring(e + 1).Trim();
                }
            }
            return a;
        }

        public string Al(string anahtar, string varsayilan = "")
        {
            string v;
            return _d.TryGetValue(anahtar, out v) && v.Length > 0 ? v : varsayilan;
        }

        public void Ayarla(string anahtar, string deger) { _d[anahtar] = deger; }

        public void Kaydet()
        {
            var sb = new StringBuilder();
            sb.AppendLine("# OdaKartOku yukleme ayarlari");
            sb.AppendLine("# platform : github  veya  gitlab");
            sb.AppendLine();
            foreach (var kv in _d) sb.AppendLine(kv.Key + "=" + kv.Value);
            Directory.CreateDirectory(Path.GetDirectoryName(Dosya));
            File.WriteAllText(Dosya, sb.ToString(), new UTF8Encoding(true));
        }

        public static Ayarlar OrnekOlustur(string dosya)
        {
            var a = new Ayarlar { Dosya = dosya };
            a.Ayarla("platform", "github");
            a.Ayarla("sahip", "");                 // GitHub kullanici/kurum adi
            a.Ayarla("depo", "");                  // GitHub depo adi
            a.Ayarla("dal", "main");
            a.Ayarla("hedef_klasor", "kayitlar");  // depo icindeki klasor
            a.Ayarla("gitlab_sunucu", "https://gitlab.com");
            a.Ayarla("gitlab_proje_id", "");       // GitLab proje ID veya yol
            a.Kaydet();
            return a;
        }
    }

    #endregion

    #region Guvenli jeton saklama

    internal static class Jeton
    {
        private static readonly byte[] Tuz = Encoding.UTF8.GetBytes("OdaKartOku-v1");

        public static void Kaydet(string dosya, string jeton)
        {
            byte[] ham = Encoding.UTF8.GetBytes(jeton);
            byte[] sifreli = ProtectedData.Protect(ham, Tuz, DataProtectionScope.CurrentUser);
            Directory.CreateDirectory(Path.GetDirectoryName(dosya));
            File.WriteAllBytes(dosya, sifreli);
        }

        public static string Oku(string dosya)
        {
            if (!File.Exists(dosya)) return null;
            try
            {
                byte[] sifreli = File.ReadAllBytes(dosya);
                byte[] ham = ProtectedData.Unprotect(sifreli, Tuz, DataProtectionScope.CurrentUser);
                return Encoding.UTF8.GetString(ham);
            }
            catch { return null; }
        }
    }

    #endregion

    internal static class Yukleyici
    {
        /// <summary>Klasoru zipler. Var olan zip dosyasinin uzerine yazar.</summary>
        public static string Ziple(string kaynakKlasor, string zipKlasoru, out string hata)
        {
            hata = null;
            try
            {
                if (!Directory.Exists(kaynakKlasor)) { hata = "Klasor yok: " + kaynakKlasor; return null; }

                var dosyalar = Directory.GetFiles(kaynakKlasor, "*.pdf");
                if (dosyalar.Length == 0) { hata = "Klasorde PDF yok: " + kaynakKlasor; return null; }

                Directory.CreateDirectory(zipKlasoru);
                string ad = new DirectoryInfo(kaynakKlasor).Name;
                string zip = Path.Combine(zipKlasoru, ad + ".zip");
                if (File.Exists(zip)) File.Delete(zip);

                using (var arsiv = ZipFile.Open(zip, ZipArchiveMode.Create))
                    foreach (var d in dosyalar)
                        arsiv.CreateEntryFromFile(d, Path.GetFileName(d), CompressionLevel.Optimal);

                return zip;
            }
            catch (Exception ex) { hata = ex.Message; return null; }
        }

        public static bool Yukle(string zipDosya, Ayarlar ayar, string jeton, out string hata)
        {
            hata = null;
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;

            string platform = ayar.Al("platform", "github").ToLowerInvariant();
            string hedefKlasor = ayar.Al("hedef_klasor", "kayitlar").Trim('/');
            string dosyaAdi = Path.GetFileName(zipDosya);
            string depoYolu = (hedefKlasor.Length > 0 ? hedefKlasor + "/" : "") + dosyaAdi;

            byte[] icerik;
            try { icerik = File.ReadAllBytes(zipDosya); }
            catch (Exception ex) { hata = "Zip okunamadi: " + ex.Message; return false; }
            string b64 = Convert.ToBase64String(icerik);

            if (platform == "gitlab") return GitLabaYukle(ayar, jeton, depoYolu, b64, out hata);
            return GitHubaYukle(ayar, jeton, depoYolu, b64, out hata);
        }

        // ---------------- GitHub ----------------
        private static bool GitHubaYukle(Ayarlar ayar, string jeton, string depoYolu, string b64, out string hata)
        {
            hata = null;
            string sahip = ayar.Al("sahip");
            string depo = ayar.Al("depo");
            string dal = ayar.Al("dal", "main");
            if (sahip.Length == 0 || depo.Length == 0) { hata = "ayarlar.ini icinde 'sahip' ve 'depo' bos"; return false; }

            string url = "https://api.github.com/repos/" + sahip + "/" + depo + "/contents/" + depoYolu;

            // Ayni dosya varsa guncellemek icin SHA gerekir
            string sha = GitHubSha(url + "?ref=" + dal, jeton);

            var govde = new StringBuilder();
            govde.Append("{\"message\":\"").Append(JsonKacis("Oda kayitlari " + DateTime.Now.ToString("dd.MM.yyyy HH:mm"))).Append("\"");
            govde.Append(",\"content\":\"").Append(b64).Append("\"");
            govde.Append(",\"branch\":\"").Append(JsonKacis(dal)).Append("\"");
            if (sha != null) govde.Append(",\"sha\":\"").Append(sha).Append("\"");
            govde.Append("}");

            string yanit;
            if (!Istek("PUT", url, govde.ToString(), jeton, true, out yanit, out hata)) return false;
            return true;
        }

        private static string GitHubSha(string url, string jeton)
        {
            string yanit, h;
            if (!Istek("GET", url, null, jeton, true, out yanit, out h)) return null;
            int i = yanit.IndexOf("\"sha\"", StringComparison.Ordinal);
            if (i < 0) return null;
            int b = yanit.IndexOf('"', yanit.IndexOf(':', i) + 1);
            int s = yanit.IndexOf('"', b + 1);
            if (b < 0 || s < 0) return null;
            return yanit.Substring(b + 1, s - b - 1);
        }

        // ---------------- GitLab ----------------
        private static bool GitLabaYukle(Ayarlar ayar, string jeton, string depoYolu, string b64, out string hata)
        {
            hata = null;
            string sunucu = ayar.Al("gitlab_sunucu", "https://gitlab.com").TrimEnd('/');
            string proje = ayar.Al("gitlab_proje_id");
            string dal = ayar.Al("dal", "main");
            if (proje.Length == 0) { hata = "ayarlar.ini icinde 'gitlab_proje_id' bos"; return false; }

            string url = sunucu + "/api/v4/projects/" + Uri.EscapeDataString(proje) +
                         "/repository/files/" + Uri.EscapeDataString(depoYolu);

            var govde = new StringBuilder();
            govde.Append("{\"branch\":\"").Append(JsonKacis(dal)).Append("\"");
            govde.Append(",\"encoding\":\"base64\"");
            govde.Append(",\"content\":\"").Append(b64).Append("\"");
            govde.Append(",\"commit_message\":\"").Append(JsonKacis("Oda kayitlari " + DateTime.Now.ToString("dd.MM.yyyy HH:mm"))).Append("\"");
            govde.Append("}");

            string yanit, h2;
            // once olustur; zaten varsa guncelle
            if (Istek("POST", url, govde.ToString(), jeton, false, out yanit, out h2)) return true;
            if (Istek("PUT", url, govde.ToString(), jeton, false, out yanit, out hata)) return true;
            return false;
        }

        // ---------------- HTTP ----------------
        private static bool Istek(string yontem, string url, string govde, string jeton,
                                  bool github, out string yanit, out string hata)
        {
            yanit = null; hata = null;
            try
            {
                var istek = (HttpWebRequest)WebRequest.Create(url);
                istek.Method = yontem;
                istek.Timeout = 300000;
                istek.ReadWriteTimeout = 300000;
                istek.UserAgent = "OdaKartOku/1.0";
                istek.Accept = "application/json";

                if (github)
                {
                    istek.Headers["Authorization"] = "Bearer " + jeton;
                    istek.Headers["X-GitHub-Api-Version"] = "2022-11-28";
                }
                else
                {
                    istek.Headers["PRIVATE-TOKEN"] = jeton;
                }

                if (govde != null)
                {
                    byte[] veri = Encoding.UTF8.GetBytes(govde);
                    istek.ContentType = "application/json";
                    istek.ContentLength = veri.Length;
                    using (var s = istek.GetRequestStream()) s.Write(veri, 0, veri.Length);
                }

                using (var c = (HttpWebResponse)istek.GetResponse())
                using (var r = new StreamReader(c.GetResponseStream()))
                {
                    yanit = r.ReadToEnd();
                    return (int)c.StatusCode >= 200 && (int)c.StatusCode < 300;
                }
            }
            catch (WebException wex)
            {
                string detay = "";
                try
                {
                    if (wex.Response != null)
                        using (var r = new StreamReader(wex.Response.GetResponseStream()))
                            detay = r.ReadToEnd();
                }
                catch { }
                var hr = wex.Response as HttpWebResponse;
                hata = (hr != null ? ((int)hr.StatusCode) + " " + hr.StatusCode + " - " : "") +
                       wex.Message + (detay.Length > 0 ? " | " + Kisa(detay) : "");
                return false;
            }
            catch (Exception ex) { hata = ex.Message; return false; }
        }

        private static string JsonKacis(string s)
        {
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "").Replace("\n", " ");
        }

        private static string Kisa(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Replace("\r", " ").Replace("\n", " ");
            return s.Length <= 300 ? s : s.Substring(0, 300) + "...";
        }
    }
}
