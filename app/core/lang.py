"""
core/lang.py
Turkce / English dil sozlukleri (Discord baglanti araci).
Kullanim: from core.lang import L, set_lang
"""

TR = {
    # Pencere
    "title":            "DPort",
    "subtitle":         "",
    "admin_yes":        "Yönetici",
    "admin_no":         "Yönetici Değil",

    # Durum panosu
    "dash_title":       "DURUM",
    "dash_path":        "Bağlantı Yolu",
    "dash_version":     "Discord Sürümü",
    "dash_dns":         "Sistem DNS",
    "dash_ping":        "Gateway Gecikmesi",
    "dash_servers":     "Açılan Sunucular",
    "val_active":       "● Aktif",
    "val_inactive":     "○ Kapalı",
    "val_auto":         "Otomatik (DHCP)",
    "val_unknown":      "Bilinmiyor",
    "val_none":         "—",
    "val_measuring":    "ölçülüyor...",
    "val_not_installed":"Discord kurulu değil",
    "servers_all":      "update · API · gateway · CDN",

    # Hero (bağlantı kartı)
    "hero_on":          "Bağlantı Açık",
    "hero_off":         "Bağlantı Kapalı",
    "hero_hint":        "Açmak için “Discord'u Aç”a bas",
    "hero_sub_on":      "Engel aşma yolu etkin",

    # Ana butonlar
    "btn_open":         "Discord'u Aç",
    "btn_opening":      "Açılıyor...",
    "btn_restore":      "Normale Dön",

    # Durum mesajları
    "st_ready":         "Hazır",
    "st_setting_dns":   "DNS ayarlanıyor (1.1.1.1)...",
    "st_path_prep":     "Bağlantı yolu hazırlanıyor...",
    "st_updating":      "Discord güncelleniyor / açılıyor...",
    "st_update_started":"Güncelleme/açılış başladı",
    "st_opening_fast":  "Discord hızlı açılıyor...",
    "st_opened":        "Discord açıldı ✓",
    "st_restoring":     "Normale dönülüyor...",
    "st_restored":      "Normale dönüldü (engel yolu kapatıldı)",
    "st_fail_port":     "Yol açılamadı (443 portu meşgul)",
    "st_fail_admin":    "Yol açılamadı (yönetici izni gerekli)",
    "st_fail_doh":      "Yol açılamadı (güvenli DNS erişimi yok)",
    "st_no_adapter":    "Aktif ağ adaptörü bulunamadı!",
    "st_not_found":     "Discord bulunamadı",
    "st_update_ok":     "Güncelleme kontrolü tamamlandı ✓",
    "st_update_fail":   "Güncelleme başarısız (engel aşılamadı)",

    # Normale dön onayı
    "dlg_restore_t":    "Normale Dön",
    "dlg_restore_msg":  "Engel aşma yolu kapatılsın ve sistem DNS'i otomatiğe (DHCP) dönsün mü?\n\nNot: Discord açıksa bağlantısı kesilebilir.",

    # Log penceresi
    "log_title":        "İşlem Logu",
    "log_clear":        "Temizle",
    "log_empty":        "Kayıt yok.\n",
    "log_confirm_t":    "Temizle",
    "log_confirm_msg":  "Tüm log kayıtları silinsin mi?",

    # Ayarlar
    "settings_title":   "Ayarlar",
    "set_tray":         "Kapatınca tepsiye küçült",
    "set_startup":      "Windows başlangıcında çalıştır",
    "set_ask":          "Kapatırken sor",
    "set_lang":         "Dil / Language",

    # Kapatma diyaloğu
    "close_title":      "DPort'u Kapat",
    "close_msg":        "Discord kullanırken DPort'u tamamen kapatırsan bağlantın kesilebilir. Ne yapmak istersin?",
    "close_tray":       "Tepside Açık Kal",
    "close_quit":       "Tamamen Kapat",
    "close_remember":   "Bunu hatırla, bir daha sorma",

    # Hakkında
    "about_title":      "Hakkında",
    "about_dev":        "Geliştirici",
    "about_email":      "E-posta",
    "about_dev_name":   "IzzmooPro",
    "about_email_addr": "IzzmooPro@gmail.com",
    "about_signature":  "İmza",
    "about_purpose":    "Discord'u engele takılmadan, hızlıca ve güncel şekilde açmanı sağlar — başka bir programa gerek kalmadan.",

    # Güncelleme
    "update_title":     "Güncelleme",
    "update_check":     "Güncellemeleri Denetle",
    "update_available": "Yeni DPort sürümü bulundu: v{version}\n\nMevcut sürüm: v{current}\n\nSetup dosyası indirilsin mi?",
    "update_current":   "DPort zaten güncel.\n\nMevcut sürüm: v{version}",
    "update_no_asset":  "v{version} sürümü bulundu ama indirilebilir setup dosyası yok.\n\nGitHub Releases sayfası açılsın mı?",
    "update_downloaded":"Güncelleme indirildi.\n\nKurulumu başlatmak ve DPort'u kapatmak ister misin?",
    "update_failed":    "Güncelleme kontrolü tamamlanamadı.",
    "st_update_checking":"Güncelleme kontrol ediliyor...",
    "st_update_downloading":"Güncelleme indiriliyor...",

    # İpuçları
    "tip_about":        "Hakkında",
    "tip_help":         "Yardım / Sorun Giderme",
    "tip_log":          "Logları Göster",
    "tip_settings":     "Ayarlar",

    # Sorun giderme penceresi
    "help_title":       "Sorun Giderme",
    "help_intro":       "Bir sorun yaşarsan sırayla şunları dene:",
    "help_items": [
        ("Discord açılmıyor / “443 portu meşgul” yazıyor",
         "Başka bir program 443 portunu kullanıyor olabilir (XAMPP, IIS, başka bir VPN/proxy). Onu kapatıp tekrar “Discord'u Aç”a bas."),
        ("“Yönetici izni gerekli” uyarısı",
         "DPort'u yönetici olarak çalıştır: kısayola sağ tık → “Yönetici olarak çalıştır”. Program hosts dosyasına yazabilmek için yönetici olmalı."),
        ("“Güvenli DNS erişimi yok” yazıyor",
         "Bulunduğun ağ 1.1.1.1'i engelliyor olabilir. Farklı bir ağ ya da telefon hotspot'u dene."),
        ("Discord hâlâ güncellenmiyor",
         "Discord'u tepsi dahil tamamen kapat, sonra DPort'ta “Discord'u Aç”a tekrar bas. Böylece güncelleyici baştan çalışır."),
        ("Discord ya da tarayıcıda discord.com hiç açılmıyor",
         "DPort'u zorla kapattıysan olur. Çözüm: DPort'u tekrar aç (açılışta otomatik düzeltir) veya “Normale Dön”e bas. En kötü ihtimalle bilgisayarı yeniden başlat — kurulu güvenlik görevi otomatik temizler."),
        ("Discord kullanırken program kapanmasın",
         "DPort'u tepside açık bırak. Bağlantı DPort üzerinden gittiği için kapatırsan Discord bağlantısı kesilebilir."),
    ],
}

EN = {
    "title":            "DPort",
    "subtitle":         "",
    "admin_yes":        "Administrator",
    "admin_no":         "Not Admin",

    "dash_title":       "STATUS",
    "dash_path":        "Connection Path",
    "dash_version":     "Discord Version",
    "dash_dns":         "System DNS",
    "dash_ping":        "Gateway Latency",
    "dash_servers":     "Unblocked Hosts",
    "val_active":       "● Active",
    "val_inactive":     "○ Off",
    "val_auto":         "Automatic (DHCP)",
    "val_unknown":      "Unknown",
    "val_none":         "—",
    "val_measuring":    "measuring...",
    "val_not_installed":"Discord not installed",
    "servers_all":      "update · API · gateway · CDN",

    "hero_on":          "Connected",
    "hero_off":         "Disconnected",
    "hero_hint":        "Press “Open Discord” to start",
    "hero_sub_on":      "Bypass path active",

    "btn_open":         "Open Discord",
    "btn_opening":      "Opening...",
    "btn_restore":      "Restore Normal",

    "st_ready":         "Ready",
    "st_setting_dns":   "Setting DNS (1.1.1.1)...",
    "st_path_prep":     "Preparing connection path...",
    "st_updating":      "Updating / opening Discord...",
    "st_update_started":"Update/launch started",
    "st_opening_fast":  "Opening Discord (fast)...",
    "st_opened":        "Discord opened ✓",
    "st_restoring":     "Restoring normal...",
    "st_restored":      "Restored (bypass path closed)",
    "st_fail_port":     "Path failed (port 443 busy)",
    "st_fail_admin":    "Path failed (admin rights needed)",
    "st_fail_doh":      "Path failed (no secure DNS access)",
    "st_no_adapter":    "No active network adapter!",
    "st_not_found":     "Discord not found",
    "st_update_ok":     "Update check complete ✓",
    "st_update_fail":   "Update failed (block not bypassed)",

    "dlg_restore_t":    "Restore Normal",
    "dlg_restore_msg":  "Close the bypass path and set system DNS back to automatic (DHCP)?\n\nNote: If Discord is open its connection may drop.",

    "log_title":        "Activity Log",
    "log_clear":        "Clear",
    "log_empty":        "No records.\n",
    "log_confirm_t":    "Clear Log",
    "log_confirm_msg":  "Delete all log entries?",

    "settings_title":   "Settings",
    "set_tray":         "Minimize to tray on close",
    "set_startup":      "Run at Windows startup",
    "set_ask":          "Ask on close",
    "set_lang":         "Dil / Language",

    "close_title":      "Close DPort",
    "close_msg":        "If you fully close DPort while using Discord, your connection may drop. What do you want to do?",
    "close_tray":       "Keep in Tray",
    "close_quit":       "Quit Fully",
    "close_remember":   "Remember this, don't ask again",

    "about_title":      "About",
    "about_dev":        "Developer",
    "about_email":      "E-mail",
    "about_dev_name":   "IzzmooPro",
    "about_email_addr": "IzzmooPro@gmail.com",
    "about_signature":  "Signature",
    "about_purpose":    "Opens Discord for you — no block, fast, and up to date, without needing any other app.",

    "update_title":     "Update",
    "update_check":     "Check for Updates",
    "update_available": "A new DPort version is available: v{version}\n\nCurrent version: v{current}\n\nDownload the setup file?",
    "update_current":   "DPort is already up to date.\n\nCurrent version: v{version}",
    "update_no_asset":  "v{version} is available but no setup file is attached.\n\nOpen GitHub Releases?",
    "update_downloaded":"The update was downloaded.\n\nStart setup and close DPort?",
    "update_failed":    "Update check could not be completed.",
    "st_update_checking":"Checking for updates...",
    "st_update_downloading":"Downloading update...",

    "tip_about":        "About",
    "tip_help":         "Help / Troubleshooting",
    "tip_log":          "Show Log",
    "tip_settings":     "Settings",

    "help_title":       "Troubleshooting",
    "help_intro":       "If something goes wrong, try these in order:",
    "help_items": [
        ("Discord won't open / “port 443 busy”",
         "Another program may be using port 443 (XAMPP, IIS, another VPN/proxy). Close it and press “Open Discord” again."),
        ("“Admin rights needed” warning",
         "Run DPort as administrator: right-click the shortcut → “Run as administrator”. It needs admin to write the hosts file."),
        ("“No secure DNS access”",
         "Your network may block 1.1.1.1. Try a different network or a phone hotspot."),
        ("Discord still won't update",
         "Fully close Discord (including the tray), then press “Open Discord” again so the updater runs from scratch."),
        ("Discord or discord.com won't open at all",
         "Happens if you force-killed DPort. Fix: reopen DPort (it auto-heals on start) or press “Restore Normal”. Worst case, restart the PC — the installed safety task cleans it up."),
        ("Keep the app open while using Discord",
         "Leave DPort in the tray. Traffic goes through DPort, so closing it may drop Discord's connection."),
    ],
}

_LANGS = {"tr": TR, "en": EN}
_current = "tr"
L: dict = TR.copy()


def set_lang(code: str):
    """'tr' veya 'en' — aktif sozlugu gunceller."""
    global _current, L
    code = code.lower()
    if code in _LANGS:
        _current = code
        L.clear()
        L.update(_LANGS[code])


def current_lang() -> str:
    return _current
