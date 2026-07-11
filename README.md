<div align="center">

# ⚡ DPort

**Discord'u Türkiye'de takılmadan, hızlı ve güncel şekilde açan küçük bir yardımcı.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6?logo=windows&logoColor=white)
![Sürüm](https://img.shields.io/badge/Sürüm-v2.8-5865F2)
![Yapımcı](https://img.shields.io/badge/Yapımcı-IzzmooPro-2ea44f)

</div>

> 🧭 **Kısaca:** DPort'u aç → **Discord'u Aç** butonuna bas → gerisini program halletsin.
> Ekstra VPN/WARP kurmana gerek yok; her şey uygulamanın kendi içinde olur.

---

## 🎯 DPort nedir?

Türkiye'de Discord açılırken yaşanan **takılmalar**, **"Update Failed"** hataları ve **yavaş açılışları** çözmek için hazırlanmış tek pencerelik bir araç. Teknik ayarlarla uğraşmadan, tek tuşla Discord'u güncel ve düşük gecikmeyle açmanı sağlar.

## ✨ Özellikler

| | Özellik |
|:--:|:--|
| 🚀 | **Tek tıkla aç** — gerekiyorsa önce günceller, sonra Discord'u başlatır |
| ⚡ | **Düşük gecikme** — bağlantı gecikmesini (ping) canlı gösterir |
| 🔄 | **Otomatik güncelleme bildirimi** — yeni sürüm çıkınca sana haber verir |
| ↩️ | **Normale Dön** — yaptığı tüm ayarları tek tuşla geri alır |
| 🛡️ | **Güvenlik ağı** — beklenmedik kapanmada sistemi otomatik onarır |
| 🌙 | **Sade modern arayüz** — koyu tema, tek pencere, tepside çalışır |

## ⬇️ İndir

Son sürümü buradan indir:

### 👉 [**En Son Sürüm (Latest Release)**](https://github.com/IzzmooPro/DPort/releases/latest)

Kurulum dosyası şu isimle görünür: **`DPort-Setup-<sürüm>.exe`**

## 🚀 Nasıl kullanılır?

1. **`DPort-Setup-x.x.exe`** ile kur (yönetici onayı ister).
2. DPort'u aç → **`Discord'u Aç`** butonuna bas.
3. Discord kullanırken **DPort'u sistem tepsisinde açık bırak.**
4. İşin bitince istersen **`Normale Dön`** ile her şeyi eski hâline al.

## 🔒 Neden yönetici izni ister?

DPort, Discord'un bağlantısını hazırlamak için bazı **Windows ağ ayarlarını** geçici olarak düzenler ve işi bitince geri alır. Yönetici izni tam olarak bunun için gerekir — gizli bir arka plan işlemi için değil.

## 🔄 Güncellemeler nasıl çalışır?

DPort açılınca GitHub'daki son sürümü kontrol eder. Yeni sürüm varsa **sana sorar**, zorla kurmaz:

1. Yeni sürümü bulur ve gösterir.
2. İndirmek isteyip istemediğini sorar.
3. İndirilen dosya **SHA256 ile doğrulanır**, sonra kurulum için tekrar onay ister.

## 🛡️ Güvenilirlik, Gizlilik ve VPN Farkı

### Neden güvenebilirsin?

- **Açık kaynak** — kodun tamamı bu depoda duruyor; hiçbir satırı gizli değil, istediğin zaman kendin okuyabilirsin.
- **Yalnızca GitHub Releases üzerinden dağıtılır** — tek resmi indirme adresi her zaman [Releases sayfası](https://github.com/IzzmooPro/DPort/releases/latest). Başka bir siteden/indirici programdan gelen bir DPort dosyasına güvenme.
- **Arkasında veri toplayan bir sunucu yok** — analitik, telemetri veya kullanıcıdan habersiz arka planda sunucuya veri gönderen bir mekanizma **yok**. Kodda dışarıyla konuşan yerler sınırlı ve hepsi işlevle ilgili — tam listesi:

  | Adres | Ne için, ne zaman |
  |:--|:--|
  | `api.github.com`, `github.com` | Yeni sürüm var mı kontrolü ve indirme (yalnızca kullanıcı onaylarsa) |
  | `1.1.1.1` (Cloudflare) | Discord adreslerinin gerçek IP'sini bulmak (DoH sorgusu) |
  | Discord'un kendi sunucuları | Discord'u açmak/güncellemek — zaten amaç bu |

  Bunların dışında hiçbir yere, hiçbir zaman veri gönderilmez. Kendi loglar bile yalnızca kendi bilgisayarındaki `dport.log` dosyasında kalır, hiçbir yere yüklenmez.
- **Güncellemeler doğrulanır, zorla kurulmaz** — indirilen kurulum dosyası GitHub'ın kendi yayınladığı **SHA256 özetiyle** karşılaştırılır; uyuşmazsa kurulum **hiç başlamaz**. Her adımda önce sana sorulur.
- **Her şey geri alınabilir** — DNS ve `hosts` değişiklikleri **Normale Dön** ile tek tuşla ya da programı kapatınca otomatik geri alınır. Beklenmedik bir çökme olsa bile, arka planda sürekli çalışan bir **güvenlik ağı** (watchdog + sonraki oturum açılışında temizleyici görev) sistemi kendiliğinden eski haline getirir — kalıcı bir iz bırakmaz.
- **Kaldırma temiz** — kaldırıcı, DPort'un eklediği her şeyi (hosts satırları, zamanlanmış temizlik görevi) söker; başka hiçbir uygulamanın ayarına dokunmaz.

> ⚠️ Program ağ ayarlarına (DNS, `hosts`) dokunduğu için Windows Defender veya bazı antivirüsler bunu **yanlışlıkla "şüpheli"** olarak işaretleyebilir (false-positive). Bu, bağlantı ayarlarını yöneten her araçta görülen normal bir durumdur; yukarıdaki maddeler nedeniyle güvenle kullanabilirsin.

### VPN'den farkı

DPort bir **VPN değildir** ve trafiğini hiçbir yere "taşımaz" — sadece Discord'u doğru yere **işaret eder**:

| | VPN | DPort |
|:--|:--|:--|
| Trafiğin nereden geçer? | Şirketin **uzak sunucusundan** (tüm internetin) | **Sadece kendi bilgisayarından** (yalnız Discord) |
| Kim görebilir? | VPN şirketi, teorik olarak tüm trafiğini | Kimse — araya hiçbir üçüncü sunucu girmiyor |
| Neyi kapsar? | Tüm internet trafiğin | Yalnızca 5 Discord adresi (güncelleme, API, gateway, CDN) |
| Şifreleme kim çözer? | VPN sunucusu (bazı VPN'lerde) | Kimse — uçtan uca şifre (TLS) Discord ile senin bilgisayarın arasında kalır |

Somut olarak DPort şunu yapar: bilgisayarında **kendi içinde**, `127.0.0.1` üzerinde küçük bir yerel röle çalıştırır; yalnızca engellenen 5 Discord adresini (`updates.discord.com`, `discord.com`, `gateway.discord.gg`, `cdn.discordapp.com`, `media.discordapp.net`) bu röleye yönlendirip, ilk bağlantı paketini (TLS ClientHello) küçük parçalara bölerek Türkiye'deki DPI engelini aşar. Röle şifreli veriyi **açmaz/okumaz** — sadece paketi Discord'un gerçek sunucusuna iletir; şifre çözme uçtan uca Discord ile senin cihazın arasında kalır. Bunun dışında yaptığı tek şey, sistem DNS'ini geçici olarak Cloudflare'in genel sunucusu **1.1.1.1**'e çevirmektir. Tarayıcı geçmişine, şifrelere, mesajlara veya Discord dışındaki hiçbir uygulamanın trafiğine dokunmaz.

## 💻 Kaynaktan Çalıştırmak

Python kuruluysa, kurulum yapmadan kaynaktan denemek için:

```bat
scripts\Calistir.bat
```

## ⚖️ Sorumluluk Reddi

DPort; yalnızca eğitim, araştırma ve kişisel kullanım amacıyla geliştirilmiş açık kaynaklı bir projedir. Ticari bir ürün olarak sunulmamaktadır.

- Yazılımın kullanımından doğabilecek doğrudan ya da dolaylı hiçbir zarardan geliştirici sorumlu tutulamaz; program **olduğu gibi** sağlanır.
- Programı kullanıp kullanmamak tamamen kullanıcının kendi tercihi ve sorumluluğundadır.
- Yürürlükteki yasa ve düzenlemelere uygun kullanım kullanıcıya aittir.
- Örnek olarak Discord'un seçilmesinin nedeni, DPI ile erişimi kısıtlanan bir uygulama üzerinde yöntemin denenebilmesi gereğidir; belirli bir hizmeti hedef alma amacı taşımaz.
- Kaynak kodun GitHub üzerinde paylaşılması, bilgi paylaşımı ve yazılım geliştirme öğrenimi amacına yöneliktir.

## 👤 Geliştirici

**IzzmooPro** · 📧 IzzmooPro@gmail.com

<div align="center">

---

*İyi sohbetler!* 💙

</div>

<br>

---

<div align="center">

# ⚡ DPort (English)

**A small helper that opens Discord in Turkey — unblocked, fast, and up to date.**

</div>

> 🧭 **In short:** open DPort → press **Open Discord** → let the app handle the rest.
> No extra VPN/WARP needed; everything happens inside the app.

## 🎯 What is DPort?

A single-window tool made to fix the **freezes**, **"Update Failed"** errors, and **slow startups** when opening Discord in Turkey. It opens Discord — updated and with low latency — in one click, without you touching any technical settings.

## ✨ Features

| | Feature |
|:--:|:--|
| 🚀 | **One-click open** — updates first if needed, then launches Discord |
| ⚡ | **Low latency** — shows the connection latency (ping) live |
| 🔄 | **Auto update notice** — tells you when a new version is out |
| ↩️ | **Restore Normal** — undoes every setting it made, in one click |
| 🛡️ | **Safety net** — auto-repairs the system after an unexpected close |
| 🌙 | **Clean modern UI** — dark theme, single window, runs in the tray |

## ⬇️ Download

Get the latest version here:

### 👉 [**Latest Release**](https://github.com/IzzmooPro/DPort/releases/latest)

The installer looks like: **`DPort-Setup-<version>.exe`**

## 🚀 How to use

1. Install with **`DPort-Setup-x.x.exe`** (asks for admin approval).
2. Open DPort → press **`Open Discord`**.
3. Keep **DPort in the system tray** while using Discord.
4. When done, use **`Restore Normal`** to revert everything if you like.

## 🔒 Why does it need administrator rights?

DPort temporarily adjusts some **Windows network settings** to prepare Discord's connection, then reverts them. Admin rights are needed exactly for that — not for any hidden background action.

## 🔄 How updates work

On start, DPort checks the latest release on GitHub. If there's a newer one, it **asks you first** — nothing is forced:

1. It finds and shows the new version.
2. It asks whether you want to download it.
3. The download is **verified with SHA256**, then it asks again before installing.

## 🛡️ Trust, Privacy, and How It Differs From a VPN

### Why you can trust it

- **Open source** — the entire codebase lives in this repo; nothing is hidden, read any line you want.
- **Distributed only via GitHub Releases** — the one official download is always the [Releases page](https://github.com/IzzmooPro/DPort/releases/latest). Don't trust a DPort file from anywhere else.
- **No server collecting your data** — there's no analytics, telemetry, or "phone-home" mechanism. The only places the code talks to the outside world are functional and listed here, in full:

  | Address | What for, and when |
  |:--|:--|
  | `api.github.com`, `github.com` | Checking for a new version and downloading it (only if you approve) |
  | `1.1.1.1` (Cloudflare) | Resolving the real IP of Discord's addresses (a DoH query) |
  | Discord's own servers | Opening/updating Discord — the whole point of the app |

  Nothing else, ever. Even its own logs stay in a local `dport.log` file on your machine — they're never uploaded anywhere.
- **Updates are verified, never forced** — the downloaded installer is checked against the **SHA256 checksum GitHub itself publishes**; if it doesn't match, installation **doesn't start**. You're asked for confirmation at every step.
- **Everything is reversible** — DNS and `hosts` changes are undone with one click (**Restore Normal**) or automatically when the app closes. Even after an unexpected crash, a background **safety net** (a watchdog plus a cleanup task on the next logon) restores the original state on its own — nothing is left behind.
- **Clean uninstall** — the uninstaller removes everything DPort added (hosts lines, the scheduled cleanup task) and touches nothing that belongs to any other app.

> ⚠️ Because the app touches network settings (DNS, `hosts`), Windows Defender or some antivirus tools may **falsely flag it as "suspicious"** (false-positive). This is normal for any tool that manages connection settings — the points above are why it's safe to use anyway.

### How it differs from a VPN

DPort is **not a VPN**, and it never "routes" your traffic anywhere — it just **points** Discord to the right place:

| | VPN | DPort |
|:--|:--|:--|
| Where does your traffic go? | Through the provider's **remote server** (your whole internet) | **Only through your own PC** (Discord only) |
| Who can see it? | The VPN company, in theory all your traffic | No one — no third-party server sits in between |
| What does it cover? | Your entire internet traffic | Just 5 Discord addresses (update, API, gateway, CDN) |
| Who decrypts it? | The VPN server (on some VPNs) | No one — end-to-end encryption (TLS) stays between Discord and your PC |

Concretely, DPort runs a tiny local relay on `127.0.0.1`, **on your own machine**. It redirects only the 5 blocked Discord addresses (`updates.discord.com`, `discord.com`, `gateway.discord.gg`, `cdn.discordapp.com`, `media.discordapp.net`) to that relay, and splits the first connection packet (TLS ClientHello) into small fragments to get past Turkey's DPI block. The relay **never opens or reads** the encrypted data — it just forwards the packet to Discord's real server; decryption stays end-to-end between Discord and your device. The only other thing it does is temporarily point your system DNS to Cloudflare's public **1.1.1.1** resolver. It never touches your browser history, passwords, messages, or the traffic of any app other than Discord.

## 💻 Run from source

If Python is installed, try it from source without installing:

```bat
scripts\Calistir.bat
```

## ⚖️ Disclaimer

DPort is an open-source project built solely for educational, research, and personal use. It is not offered as a commercial product.

- The developer cannot be held liable for any direct or indirect damage arising from the use of this software; it is provided **as is**.
- Whether or not to use the program is entirely the user's own choice and responsibility.
- Using it in accordance with applicable laws and regulations is the user's responsibility.
- Discord was chosen as an example because the method needs a service whose access is restricted via DPI to be tested against; it does not aim to target any specific service.
- Sharing the source code on GitHub serves the purpose of knowledge sharing and learning software development.

## 👤 Developer

**IzzmooPro** · 📧 IzzmooPro@gmail.com

<div align="center">

---

*Happy chatting!* 💙

</div>
