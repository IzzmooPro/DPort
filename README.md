# DPort

**DPort**, Discord'u Windows üzerinde tek ekrandan açmayı kolaylaştıran küçük bir yardımcı araçtır. DNS ayarını hazırlar, gerekli yerel bağlantı yolunu kurar ve Discord'un açılma/güncelleme sürecini daha sorunsuz hale getirmeyi hedefler.

> DPort bir VPN değildir. Discord için gerekli sistem ayarlarını ve yerel bağlantı yönlendirmesini yönetir.

## İndir / Download

Son sürümü GitHub Releases sayfasından indirebilirsin:

[Latest Release](https://github.com/IzzmooPro/DPort/releases/latest)

Kurulum dosyası adı genelde şu şekildedir:

`DPort-Setup-<version>.exe`

## Ne Yapar?

- Discord için gerekli DNS ayarlarını hazırlar.
- Discord bağlantısı için yerel yardımcı bağlantı yolunu başlatır.
- Discord'u açmadan önce bağlantı durumunu kontrol eder.
- Gerektiğinde sistemi normale döndürmek için "Normale Dön" seçeneği sunar.
- Açılışta GitHub Releases üzerinden yeni sürüm kontrolü yapar.

## Neden Yönetici İzni İster?

DPort bazı Windows ağ ayarlarını yönetir. Bu yüzden yönetici izni gerekir:

- DNS ayarını değiştirmek
- `hosts` dosyasındaki DPort bölümünü eklemek veya temizlemek
- Güvenlik amaçlı temizlik görevini yönetmek

Bu izinler Discord bağlantısını hazırlamak ve program kapandığında sistemi temiz şekilde eski haline döndürmek için kullanılır.

## Güncelleme Sistemi

DPort açıldığında GitHub Releases üzerinden yeni sürüm olup olmadığını kontrol eder. Yeni sürüm varsa kullanıcıdan onay alır:

1. Yeni sürüm bulunduğunu gösterir.
2. Setup dosyasını indirmek için izin ister.
3. İndirme tamamlanınca kurulumu başlatmak için tekrar onay ister.

Güncelleme işlemi sessiz ve zorla yapılmaz; kullanıcı onayı gerekir.

## Güven Notu

DPort açık kaynak olarak burada yayınlanır. Kurulum dosyaları GitHub Releases üzerinden paylaşılır. Windows veya antivirüs yazılımları, DNS/hosts değiştiren ve yönetici izni isteyen yardımcı araçları bazen daha dikkatli işaretleyebilir. Bu nedenle kaynak kodu ve release dosyaları birlikte kontrol edilebilir.

## Developer

Developer / Geliştirici: **IzzmooPro**

In-app signature / Uygulama içi imza: **IzzmooPro**

---

# English

**DPort** is a small Windows helper tool designed to make opening Discord easier from a single interface. It prepares the required DNS settings, starts the local connection helper path, and aims to make Discord launch/update more reliably.

> DPort is not a VPN. It manages the required Windows network settings and local routing helper for Discord.

## Download

Download the latest installer from GitHub Releases:

[Latest Release](https://github.com/IzzmooPro/DPort/releases/latest)

The installer is usually named like this:

`DPort-Setup-<version>.exe`

## What It Does

- Prepares DNS settings required for Discord.
- Starts the local helper path used by Discord connections.
- Checks connection state before opening Discord.
- Provides a "Restore Normal" option to revert the system changes it manages.
- Checks GitHub Releases for updates on startup.

## Why It Needs Administrator Rights

DPort needs administrator rights because it manages Windows network settings:

- Changing DNS settings
- Adding or removing DPort's section in the `hosts` file
- Managing the safety cleanup task

These permissions are used to prepare Discord connectivity and restore the system cleanly when needed.

## Update System

DPort checks GitHub Releases for new versions when it starts. If a new version is available, it asks for confirmation:

1. It shows that a new version is available.
2. It asks permission to download the setup file.
3. After download, it asks again before starting the installer.

Updates are not forced or installed silently; user confirmation is required.

## Safety Note

DPort is published here as open source. Installer files are distributed through GitHub Releases. Windows or antivirus tools may treat utilities that request administrator rights and modify DNS/hosts settings more carefully. For transparency, the source code and release files can be reviewed together.
