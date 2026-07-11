<div align="center">

# ⚡ DPort

**Discord'u Türkiye'de takılmadan, hızlı ve güncel şekilde açan küçük bir yardımcı.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6?logo=windows&logoColor=white)
![Sürüm](https://img.shields.io/badge/Sürüm-v2.7-5865F2)
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

## 🛡️ Güven & Antivirüs Notu

DPort **açık kaynaktır** ve kurulum dosyaları yalnızca **GitHub Releases** üzerinden paylaşılır. Kaynak kodu istediğin zaman buradan inceleyebilirsin.

> ⚠️ Program ağ ayarlarına dokunduğu için Windows Defender veya bazı antivirüsler bunu **yanlışlıkla "şüpheli"** olarak işaretleyebilir (false-positive). Bu, bağlantı ayarlarını yöneten araçlarda normaldir; güvenle kullanabilirsin.

## 💻 Kaynaktan Çalıştırmak

Python kuruluysa, kurulum yapmadan kaynaktan denemek için:

```bat
scripts\Calistir.bat
```

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

## 🛡️ Trust & Antivirus Note

DPort is **open source**, and installers are shared only via **GitHub Releases**. You can review the source code here any time.

> ⚠️ Because the app touches network settings, Windows Defender or some antivirus tools may **falsely flag it as "suspicious"** (false-positive). This is normal for tools that manage connection settings — it's safe to use.

## 💻 Run from source

If Python is installed, try it from source without installing:

```bat
scripts\Calistir.bat
```

## 👤 Developer

**IzzmooPro** · 📧 IzzmooPro@gmail.com

<div align="center">

---

*Happy chatting!* 💙

</div>
