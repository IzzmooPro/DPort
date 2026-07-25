<div align="center">

# ⚡ DPort

**Discord'un açılmadığı ya da güncellenmediği durumlarda, başka bir program kurmadan bağlanmanı sağlayan küçük bir Windows aracı.**

![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6?logo=windows&logoColor=white)
![Sürüm](https://img.shields.io/badge/Sürüm-v3.7-5865F2)
![Yapımcı](https://img.shields.io/badge/Yapımcı-IzzmooPro-2ea44f)

### ⬇️ [**DPort v3.7'yi İndir**](https://github.com/IzzmooPro/DPort/releases/latest)

<sub>İndirilecek dosya: `DPort-Setup-3.7.exe`</sub>

</div>

---

## DPort ne yapar?

Bazı ağlarda Discord açılmaz, takılır veya güncellemesini bitiremez. DPort, Discord'un bağlanmak için kullandığı yolu düzelterek bu sorunu aşmayı dener.

Tek bir düğmesi vardır: **Discord'u Aç**. İşin bittiğinde **Normale Dön** düğmesi yaptığı değişiklikleri geri alır.

---

## Üç adımda kullan

**1. İndir ve kur**
[Son sürümü indir](https://github.com/IzzmooPro/DPort/releases/latest) ve `DPort-Setup-3.7.exe` dosyasını çalıştır. Windows yönetici onayı isteyecek.

**2. DPort'u aç**
Masaüstü kısayolundan başlat. Tek pencerelik, sade bir arayüz açılır.

**3. "Discord'u Aç" düğmesine bas**
DPort gerekli ayarları yapar ve Discord'u başlatır. İşin bitince **Normale Dön**'e basabilirsin.

> Discord'u kullanırken DPort'un açık kalması gerekir — bağlantı onun üzerinden gittiği için kapatırsan Discord'un bağlantısı kesilebilir. Pencereyi kapatınca tepside açık bırakabilirsin.

---

## Bilgisayarında neyi değiştirir?

DPort üç şeye dokunur. Üçü de **Normale Dön** ile veya program kapanınca geri alınır:

| Ne | Ne için | Geri alınır mı? |
|---|---|---|
| **DNS ayarı** | Ağ adaptörünün DNS'ini Cloudflare'e (`1.1.1.1`) çevirir, böylece Discord adresleri doğru çözülür | Evet — orijinal ayarın yedeklenir ve aynen geri yüklenir |
| **`hosts` dosyası** | Yalnızca 5 Discord adresini kendi bilgisayarına yönlendirir | Evet — yalnızca kendi eklediği işaretli satırları siler, diğer satırlarına dokunmaz |
| **Yerel röle** | Bilgisayarında küçük bir aktarıcı çalıştırır ve Discord trafiğini oradan geçirir | Evet — program kapanınca durur |

Yönlendirilen adresler: `discord.com`, `updates.discord.com`, `gateway.discord.gg`, `cdn.discordapp.com`, `media.discordapp.net`.

DPort beklenmedik şekilde kapanırsa (çökme, görev yöneticisinden kapatma), `hosts` değişikliğini bir sonraki açılışta veya oturum açışında otomatik temizlemeye çalışır.

---

## Neden yönetici izni istiyor?

Dürüst cevap: **yapmak istediği şeyler yönetici hakkı olmadan yapılamaz.**

- Ağ adaptörünün **DNS ayarını değiştirmek** yönetici gerektirir.
- Windows'un **`hosts` dosyası** korumalı bir sistem dosyasıdır; yazmak için yönetici gerekir.
- **443 numaralı portu** dinlemek yönetici gerektirir.
- Çökme sonrası temizlik yapan **zamanlanmış görevi** kurmak yönetici gerektirir.

Bunlar programın tamamının yaptığı iştir; başka bir amaçla yükseltilmiş yetki kullanılmaz. Ne yaptığını kendi gözünle görmek istersen kaynak kodu bu depoda.

---

## ⚠️ Windows "Bilinmeyen yayıncı" diyebilir

**DPort'un dijital imzası (kod imzalama sertifikası) yoktur.** Bu yüzden kurulumda Windows SmartScreen uyarısı çıkabilir ve UAC penceresinde yayıncı adı **"Bilinmeyen"** görünebilir.

Bu normaldir ve sertifikanın ücretli olmasından kaynaklanır — programın bozuk veya zararlı olduğu anlamına gelmez, ama **imza olmadığı için Windows dosyanın kaynağını senin adına doğrulayamaz.** Bu yüzden:

- Dosyayı **yalnızca** [resmî Releases sayfasından](https://github.com/IzzmooPro/DPort/releases/latest) indir.
- Başka sitelerden indirilen "DPort" dosyalarına güvenme.

---

## Gizlilik

Aşağıdakiler bu depodaki kaynak kodda doğrulanabilir:

- **Telemetri, analiz veya kullanım takibi yok.** Kodda hiçbir analiz kütüphanesi bulunmuyor ve program hiçbir yere veri gönderen istek (POST/PUT) yapmıyor.
- **Parolanı, mesajlarını veya Discord hesabını okumaz.** Yerel röle şifrelenmiş trafiği çözmez; sertifika üretmez ve TLS bağlantısını sonlandırmaz. Discord ile sunucuları arasındaki şifreleme uçtan uca korunur — röle sadece paketleri aktarır.
- **Kayıt tutar ama yalnızca senin bilgisayarında.** Log dosyası hangi işlemin yapıldığını yazar (ör. "DNS ayarlandı"); hiçbir yere yüklenmez ve arayüzden temizleyebilirsin.

DPort'un internete çıktığı yerler bunlarla sınırlıdır:

| Adres | Ne için |
|---|---|
| `1.1.1.1` (Cloudflare) | Discord adreslerinin IP'sini çözmek |
| `api.github.com`, `github.com` | Yeni sürüm var mı kontrolü ve (sen onaylarsan) indirme |
| Discord adresleri | Yukarıdaki tabloda listelenen bağlantıların aktarılması |

---

## DPort bir VPN değildir

Bunu net söylemek gerekir:

- **IP adresini gizlemez.** Bağlandığın sunucular gerçek IP'ni görmeye devam eder.
- **Anonimlik sağlamaz.** İnternet servis sağlayıcın bir Discord bağlantısı kurduğunu görebilir.
- **Diğer programların trafiğini etkilemez.** Yalnızca yukarıda listelenen Discord adreslerini kapsar.
- **Her ağda çalışacağının garantisi yoktur.** Yöntem bazı ağlarda sonuç vermeyebilir.

Amacı gizlenmek değil, Discord'un bağlantısını çalışır hale getirmektir.

---

## Güncellemeler

DPort açılınca GitHub'daki son sürümü kontrol eder. Yeni sürüm varsa **sana sorar** — onayın olmadan indirmez veya kurmaz.

İndirilen kurulum dosyasının **SHA-256 özeti**, GitHub'ın o dosya için yayınladığı değerle karşılaştırılır. Uyuşmazsa dosya **çalıştırılmaz**. Doğrulama ile çalıştırma arasında dosyanın değiştirilememesi için dosya kilitli tutulur.

---

## v3.7'de ne değişti?

Bu sürüm güvenlik sertleştirmelerine odaklandı:

- **Discord artık normal kullanıcı yetkisiyle açılıyor** — DPort yönetici olarak çalışsa bile Discord bu yetkiyi devralmıyor.
- **Güncelleme dosyası korumalı bir klasöre iniyor**, SHA-256 ile doğrulanıyor ve doğrulanan dosyanın ta kendisi çalıştırılıyor.
- **DNS yedeği korumalı bir konumda saklanıyor**, böylece başka bir program onu değiştirip DPort'a yanlış ayar uygulatamıyor.
- **Çökme sonrası temizlik görevi** yalnızca doğrulanmış kurulum klasörünü hedefliyor; kurulum ve güncellemede eski görevler temizleniyor.
- **Dosya ve arayüz kaynakları** daha düzenli kapatılıyor.

---

<details>
<summary><b>🔧 Teknik ayrıntılar</b></summary>

<br>

**Yöntem.** Engelleme genellikle TLS `ClientHello` paketindeki sunucu adı (SNI) görülerek yapılır. DPort, `hosts` üzerinden ilgili adresleri `127.0.0.1`'e yönlendirir; kendi rölesi bağlantıyı alır, gerçek IP'yi DoH (`https://1.1.1.1/dns-query`) ile çözer ve `ClientHello`'yu TLS kayıt katmanında küçük parçalara bölerek gönderir. Sonrası şeffaf bir TCP tünelidir; TLS uçtan uca istemci ile Discord sunucusu arasında kalır.

**Röle sınırları.** Röle yalnızca `127.0.0.1:443` üzerinde dinler ve yalnızca yukarıda listelenen Discord adreslerine tünel açar (allowlist). SNI okunamazsa güvenli varsayılana düşer, listede olmayan hedef reddedilir.

**Geri alma yolları.** Program kapanışı, tepsiden çıkış, çalışan bir watchdog, açılıştaki kendi kendini onarma ve oturum açılışında çalışan bir zamanlanmış görev — beşi birlikte `hosts` kalıntısını temizlemeye çalışır. DNS için orijinal ayar (statik ya da otomatik) yedeklenir ve aynen geri yüklenir; DPort'un dokunmadığı adaptörlere karışılmaz.

**Kaldırma.** Kaldırıcı `hosts` bloğunu siler ve zamanlanmış görevi kaldırır. Kullanıcı ayarların (`%APPDATA%\DPort`) silinmez.

**Diğer DPI/bypass araçları.** WARP, Zapret, GoodbyeDPI gibi araçlar aynı anda çalışıyorsa çakışma olabilir. Sorun yaşarsan birini kapatıp dene.

</details>

<details>
<summary><b>💻 Kaynaktan çalıştırmak</b></summary>

<br>

```bash
git clone https://github.com/IzzmooPro/DPort.git
cd DPort
pip install -r requirements.txt
python app/main.py
```

Gereksinimler: Windows 10/11 ve Python 3.10+. Program yönetici onayı ister.

Testler:

```bash
python -m unittest discover -s tests
```

</details>

<details>
<summary><b>🇬🇧 English summary</b></summary>

<br>

**DPort** is a small Windows tool that helps Discord connect and update on networks where it otherwise fails. One button — **Open Discord** — and **Restore Normal** to undo.

**Download:** [latest release](https://github.com/IzzmooPro/DPort/releases/latest) (`DPort-Setup-3.7.exe`).

**What it changes:** your adapter's DNS (to Cloudflare `1.1.1.1`), five Discord entries in the Windows `hosts` file, and a small local relay on `127.0.0.1:443`. All three are reverted by *Restore Normal* or when the app closes.

**Why administrator rights:** changing DNS, writing to `hosts`, listening on port 443 and registering the cleanup scheduled task all require them. That is the whole job of the program.

**Not digitally signed.** Windows SmartScreen may warn you and show "Unknown publisher". Only download from the official Releases page above.

**Privacy** (verifiable in this source code): no telemetry or analytics, no requests that upload data, and the relay does not decrypt traffic — it terminates no TLS and creates no certificates, so Discord's end-to-end encryption is preserved. Logs stay on your machine.

**Not a VPN.** It does not hide your IP, does not provide anonymity, and does not cover other applications' traffic.

**Updates** are checked against GitHub, always ask before installing, and the downloaded installer is verified with SHA-256 before it is allowed to run.

</details>

---

## ⚖️ Sorumluluk reddi

DPort kişisel kullanım için yazılmış bir araçtır ve **olduğu gibi** sunulur. Kullanım sorumluluğu kullanıcıya aittir. Sistem ayarlarını (DNS ve `hosts`) değiştirdiği için ne yaptığını okuyarak kullanmanı öneririm. Bulunduğun ülkenin ve ağının kurallarına uymak senin sorumluluğundadır.

Kaynak kodu bu depoda incelenebilir.

## 👤 Geliştirici

**IzzmooPro** — sorun bildirimi ve öneriler için [Issues](https://github.com/IzzmooPro/DPort/issues) sayfasını kullanabilirsin.
