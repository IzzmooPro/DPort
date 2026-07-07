# DPort

**DPort**, Discord'u Windows üzerinde daha kolay ve sorunsuz açmak için hazırlanmış küçük bir yardımcı programdır. Tek ekrandan çalışır, gerekli bağlantı hazırlığını yapar ve işin teknik kısmını kullanıcıya bırakmadan Discord'u açmana yardımcı olur.

> Kısaca: DPort'u aç, **Discord'u Aç** butonuna bas, gerisini program yönetsin.

## İndir / Download

Son sürümü buradan indirebilirsin:

[Latest Release](https://github.com/IzzmooPro/DPort/releases/latest)

Kurulum dosyası genelde şu isimle görünür:

`DPort-Setup-<version>.exe`

## Ne İşe Yarar?

- Discord'un açılması için gerekli bağlantı hazırlığını yapar.
- Gerekirse Discord'u açmadan önce sistemi uygun hale getirir.
- Tek tuşla Discord'u başlatmayı hedefler.
- İstersen **Normale Dön** ile yaptığı ayarları geri alır.
- Yeni sürüm çıktığında bunu sana bildirir.

## Neden Yönetici İzni İster?

DPort bazı Windows bağlantı ayarlarını düzenlediği için yönetici izni ister. Bu izin, programın görevini yapabilmesi ve gerektiğinde sistemi eski haline döndürebilmesi için gerekir.

Program bu izni arka planda gizli bir işlem yapmak için değil, Discord bağlantısını hazırlamak ve temiz şekilde geri almak için kullanır.

## Güncellemeler Nasıl Çalışır?

DPort açıldığında yeni sürüm olup olmadığını kontrol eder. Yeni sürüm varsa sana sorar:

1. Yeni sürüm bulunduğunu gösterir.
2. İndirmek isteyip istemediğini sorar.
3. İndirme bitince kurulumu başlatmak için tekrar onay ister.

Yani güncellemeler zorla kurulmaz. Her adımda kullanıcı onayı gerekir.

## Güven Notu

DPort açık kaynak olarak burada yayınlanır. Kurulum dosyaları GitHub Releases üzerinden paylaşılır. Program yönetici izni istediği için Windows veya bazı antivirüsler daha dikkatli davranabilir; bu tür uyarılar, programın bağlantı ayarlarını yönetmesinden kaynaklanabilir.

İstersen kaynak kodu ve yayınlanan kurulum dosyalarını buradan kontrol edebilirsin.

## Geliştirici

Geliştirici: **IzzmooPro**

Uygulama içi imza: **IzzmooPro**

---

# English

**DPort** is a small Windows helper app made to open Discord more easily and reliably. It works from a simple interface, prepares the required connection setup, and helps you start Discord without dealing with the technical details yourself.

> In short: open DPort, press **Open Discord**, and let the app handle the rest.

## Download

Download the latest version here:

[Latest Release](https://github.com/IzzmooPro/DPort/releases/latest)

The installer usually looks like this:

`DPort-Setup-<version>.exe`

## What Does It Do?

- Prepares the connection setup needed for Discord.
- Gets the system ready before opening Discord when needed.
- Aims to open Discord with one button.
- Lets you use **Restore Normal** to undo the settings it manages.
- Notifies you when a new version is available.

## Why Does It Need Administrator Rights?

DPort asks for administrator rights because it adjusts some Windows connection settings. This permission is needed so the app can do its job and restore things cleanly when needed.

It does not use this permission for hidden background actions; it uses it to prepare Discord connectivity and undo its own changes safely.

## How Updates Work

When DPort starts, it checks whether a newer version is available. If there is one, it asks you first:

1. It shows that a new version is available.
2. It asks whether you want to download it.
3. After the download, it asks again before starting the installer.

Updates are not forced. Every step requires user confirmation.

## Safety Note

DPort is published here as open source. Installer files are shared through GitHub Releases. Because the app asks for administrator rights, Windows or some antivirus tools may be extra cautious; this can happen with tools that manage connection settings.

You can review the source code and release files here whenever you want.
