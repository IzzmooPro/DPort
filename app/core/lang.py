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
    "dash_version":     "Kurulu Discord Sürümü",
    "dash_dns":         "Sistem DNS",
    "dash_servers":     "Yönlendirilen Adresler",
    "dash_uptime":      "Aktif Süre",
    "val_active":       "● Aktif",
    "val_inactive":     "○ Kapalı",
    "val_auto":         "Otomatik (DHCP)",
    "val_unknown":      "Bilinmiyor",
    "val_none":         "—",
    "val_not_installed":"Discord kurulu değil",
    "servers_all":      "update·API·gateway·CDN",

    # Hero (bağlantı kartı)
    "hero_on":          "Bağlandı",
    "hero_off":         "Bağlantı Kapalı",
    "hero_connecting":  "Bağlanıyor…",
    "hero_hint":        "Yolu etkinleştir; Discord'u kendin aç",
    "hero_sub_on":      "Engel aşma yolu etkin",

    # Ana butonlar
    "btn_activate":     "Bağlantıyı Etkinleştir",
    "btn_activating":   "Etkinleştiriliyor...",
    "btn_restore":      "Varsayılana Dön",
    "btn_restoring":    "Geri Alınıyor...",

    # Durum mesajları
    "st_ready":         "Hazır",
    "st_activated":     "Bağlantı yolu etkin. Discord'u siz açabilirsiniz.",
    "st_setting_dns":   "DNS ayarlanıyor (1.1.1.1)...",
    "st_path_prep":     "Bağlantı yolu hazırlanıyor...",
    "st_updating":      "Discord güncelleniyor / açılıyor...",
    "st_update_started":"Güncelleme/açılış başladı",
    "st_upd_checking":   "Discord güncelleme kontrol ediliyor…",
    "st_upd_downloading":"Discord güncellemesi indiriliyor…",
    "st_upd_installing": "Discord modülleri yükleniyor…",
    "st_upd_finishing":  "Güncelleme tamamlanıyor…",
    "st_opening_fast":  "Discord hızlı açılıyor...",
    "st_opened":        "Discord açıldı",
    "st_restoring":     "Varsayılan ayarlara dönülüyor...",
    "st_restored":      "Varsayılan ayarlara dönüldü",
    "st_restore_partial": "Bazı ayarlar geri alınamadı; tekrar dene",
    "st_fail_port":     "Yol açılamadı (443 portu meşgul)",
    "st_fail_admin":    "Yol açılamadı (yönetici izni gerekli)",
    "st_fail_hosts_locked": "hosts dosyası şu an başka bir süreç tarafından kullanılıyor olabilir; birkaç saniye sonra tekrar deneyin",
    "st_fail_doh":      "Yol açılamadı (güvenli DNS erişimi yok)",
    "st_fail_failsafe": "Yol açılamadı (güvenlik görevi kurulamadı; hosts dosyasına dokunulmadı)",
    "st_fail_no_recovery": "DPort'un kurulu uygulama dosyası bulunamadı. Programı yeniden kurun.",
    "st_no_adapter":    "Aktif ağ adaptörü bulunamadı!",
    "st_not_found":     "Discord bulunamadı",
    "st_update_ok":     "Güncelleme kontrolü tamamlandı",
    "discord_ver_checking": "Kontrol ediliyor",
    "discord_ver_updating": "Güncelleniyor",
    "discord_ver_restart":  "Yeniden başlat",
    "discord_ver_updated":  "Güncellendi",
    "st_update_fail":   "Güncelleme başarısız (engel aşılamadı)",
    "st_discord_restarting": "Discord yeni yol için yeniden başlatılıyor...",
    "st_restart_close_failed": "Discord kapatılamadı, mevcut durumu korundu",
    "st_restart_close_timeout": "Discord zamanında kapanmadı, yeniden başlatma iptal edildi",
    "st_restart_launch_failed": "Discord kapatıldı ama yeniden başlatılamadı",

    # Temali dialog butonlari
    "dlg_yes":          "Evet",
    "dlg_no":           "Hayır",
    "dlg_ok":           "Tamam",

    # Ilk acilis bilgilendirmesi
    "av_notice_title":  "Antivirüs Bilgilendirmesi",
    "av_notice_msg":    "Bazı antivirüsler DPort'un çalışmasını engelleyebilir. Bağlantı etkinleşmezse antivirüsü geçici olarak duraklatıp tekrar deneyin. Ardından korumayı yeniden açın.\n\nDPort artık Discord'u otomatik açmaz. Bağlantıyı etkinleştirdikten sonra Discord'u kendi kısayolundan açın.",
    "av_notice_hide":   "Bir daha gösterme",
    "av_notice_ok":     "Anladım",

    # Varsayilana don onayi
    "dlg_restore_t":    "Varsayılana Dön",
    "dlg_restore_msg":  "Engel aşma yolu kapatılsın ve sistem DNS'i otomatiğe (DHCP) dönsün mü?\n\nNot: Discord açıksa bağlantısı kesilebilir.",
    "dlg_legacy_dns_t":   "Eski DNS Yedeği",
    "dlg_legacy_dns_msg": "Önceki bir DPort sürümünden kalan DNS yedeği bulundu:\n\n{details}\n\nBu yedek, standart kullanıcı tarafından değiştirilebilen bir dosyada tutuluyordu; DPort doğruluğunu garanti edemez. Bu yüzden otomatik uygulanmadı.\n\nDeğerler sana doğru görünüyorsa sistem DNS'i bunlara döndürülsün mü?\n\nEmin değilsen “Hayır” seç — DNS'e dokunulmaz ve yedek silinir.",
    "legacy_dns_dhcp":    "Otomatik (DHCP)",

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
    "about_version":    "Sürüm",
    "about_dev":        "Geliştirici",
    "about_email":      "E-posta",
    "about_dev_name":   "IzzmooPro",
    "about_email_addr": "IzzmooPro@gmail.com",
    "about_purpose":    "Discord bağlantı yolunu etkinleştirir; Discord'u ne zaman açacağına sen karar verirsin.",

    # Güncelleme
    "update_title":     "Güncelleme",
    "update_check":     "Güncellemeleri Denetle",
    "update_available": "Yeni DPort sürümü bulundu: v{version}\n\nMevcut sürüm: v{current}\n\nSetup dosyası indirilsin mi?",
    "update_current":   "DPort zaten güncel.\n\nMevcut sürüm: v{version}",
    "update_no_asset":  "v{version} sürümü bulundu ama indirilebilir setup dosyası yok.\n\nGitHub Releases sayfası açılsın mı?",
    "update_downloaded":"Güncelleme indirildi.\n\nKurulumu başlatmak ve DPort'u kapatmak ister misin?",
    "update_failed":    "Güncelleme kontrolü tamamlanamadı.",
    "update_verify_failed": "İndirilen güncelleme doğrulanamadı; güvenlik için çalıştırılmadı.",
    "update_staging_failed": "Güncelleme için korumalı indirme klasörü hazırlanamadı.\n\nGüvenlik gereği güncelleme, standart kullanıcının değiştirebileceği bir klasöre indirilmez. Kurulumu GitHub Releases sayfasından elle yapabilirsin.",
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
        ("Bağlantı yolu etkinleşmiyor / “443 portu meşgul” yazıyor",
         "Başka bir program 443 portunu kullanıyor olabilir (XAMPP, IIS, başka bir VPN/proxy). Onu kapatıp tekrar “Bağlantıyı Etkinleştir”e bas."),
        ("“Yönetici izni gerekli” uyarısı",
         "DPort'u yönetici olarak çalıştır: kısayola sağ tık → “Yönetici olarak çalıştır”. Program hosts dosyasına yazabilmek için yönetici olmalı."),
        ("“Güvenli DNS erişimi yok” yazıyor",
         "Bilgisayarın tarih-saatini kontrol et. Antivirüsündeki HTTPS/şifreli bağlantı taramasını geçici olarak kapatıp yeniden dene; olmazsa farklı bir ağ ya da telefon hotspot'u kullan."),
        ("“Aktif ağ adaptörü bulunamadı” yazıyor",
         "İnternet bağlantın kapalı olabilir. Wi-Fi ya da kablolu (Ethernet) bağlantının açık ve bağlı olduğundan emin olup tekrar “Bağlantıyı Etkinleştir”e bas."),
        ("“Discord bulunamadı” yazıyor",
         "Discord bilgisayarında kurulu değil ya da farklı bir konuma kurulmuş olabilir. discord.com'dan indirip kurduktan sonra tekrar dene."),
        ("Discord hâlâ açılmıyor",
         "Önce DPort'ta “Bağlantıyı Etkinleştir”e bas, ardından Discord'u kendi kısayolundan aç. Sorun sürerse Discord'u tepsi dahil tamamen kapatıp tekrar dene."),
        ("Discord ya da tarayıcıda discord.com hiç açılmıyor",
         "DPort'u zorla kapattıysan olur. Çözüm: DPort'u tekrar aç (açılışta otomatik düzeltir) veya “Varsayılana Dön”e bas. En kötü ihtimalle bilgisayarı yeniden başlat — kurulu güvenlik görevi otomatik temizler."),
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
    "dash_version":     "Installed Discord Version",
    "dash_dns":         "System DNS",
    "dash_servers":     "Routed Hosts",
    "dash_uptime":      "Active Time",
    "val_active":       "● Active",
    "val_inactive":     "○ Off",
    "val_auto":         "Automatic (DHCP)",
    "val_unknown":      "Unknown",
    "val_none":         "—",
    "val_not_installed":"Discord not installed",
    "servers_all":      "update·API·gateway·CDN",

    "hero_on":          "Connected",
    "hero_off":         "Disconnected",
    "hero_connecting":  "Connecting…",
    "hero_hint":        "Enable the path, then open Discord yourself",
    "hero_sub_on":      "Bypass path active",

    "btn_activate":     "Enable Connection",
    "btn_activating":   "Enabling...",
    "btn_restore":      "Restore Defaults",
    "btn_restoring":    "Restoring...",

    "st_ready":         "Ready",
    "st_activated":     "Connection path enabled. You can open Discord yourself.",
    "st_setting_dns":   "Setting DNS (1.1.1.1)...",
    "st_path_prep":     "Preparing connection path...",
    "st_updating":      "Updating / opening Discord...",
    "st_update_started":"Update/launch started",
    "st_upd_checking":   "Checking Discord for updates…",
    "st_upd_downloading":"Downloading Discord update…",
    "st_upd_installing": "Installing Discord modules…",
    "st_upd_finishing":  "Finishing update…",
    "st_opening_fast":  "Opening Discord (fast)...",
    "st_opened":        "Discord opened",
    "st_restoring":     "Restoring default settings...",
    "st_restored":      "Default settings restored",
    "st_restore_partial": "Some settings could not be restored; try again",
    "st_fail_port":     "Path failed (port 443 busy)",
    "st_fail_admin":    "Path failed (admin rights needed)",
    "st_fail_hosts_locked": "The hosts file may be in use by another process right now; try again in a few seconds",
    "st_fail_doh":      "Path failed (no secure DNS access)",
    "st_fail_failsafe": "Path failed (safety task could not be created; hosts file was left untouched)",
    "st_fail_no_recovery": "Installed DPort application was not found. Reinstall DPort.",
    "st_no_adapter":    "No active network adapter!",
    "st_not_found":     "Discord not found",
    "st_update_ok":     "Update check complete",
    "discord_ver_checking": "Checking for updates",
    "discord_ver_updating": "Updating",
    "discord_ver_restart":  "Restart Discord",
    "discord_ver_updated":  "Updated",
    "st_update_fail":   "Update failed (block not bypassed)",
    "st_discord_restarting": "Restarting Discord for the new path...",
    "st_restart_close_failed": "Couldn't close Discord, kept its current state",
    "st_restart_close_timeout": "Discord didn't close in time, restart cancelled",
    "st_restart_launch_failed": "Discord was closed but could not be restarted",

    "dlg_yes":          "Yes",
    "dlg_no":           "No",
    "dlg_ok":           "OK",

    "av_notice_title":  "Antivirus Information",
    "av_notice_msg":    "Some antivirus products may block DPort. If the connection cannot be enabled, pause the antivirus temporarily and try again. Turn protection back on afterward.\n\nDPort no longer opens Discord automatically. After enabling the connection, open Discord from its own shortcut.",
    "av_notice_hide":   "Don't show again",
    "av_notice_ok":     "Got it",

    "dlg_restore_t":    "Restore Defaults",
    "dlg_restore_msg":  "Close the bypass path and set system DNS back to automatic (DHCP)?\n\nNote: If Discord is open its connection may drop.",
    "dlg_legacy_dns_t":   "Legacy DNS Backup",
    "dlg_legacy_dns_msg": "A DNS backup left over from an earlier DPort version was found:\n\n{details}\n\nThat backup was kept in a file a standard user can modify, so DPort cannot vouch for it. It was therefore not applied automatically.\n\nIf these values look right to you, restore system DNS to them?\n\nIf you are unsure choose “No” — DNS is left untouched and the backup is discarded.",
    "legacy_dns_dhcp":    "Automatic (DHCP)",

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
    "about_version":    "Version",
    "about_dev":        "Developer",
    "about_email":      "E-mail",
    "about_dev_name":   "IzzmooPro",
    "about_email_addr": "IzzmooPro@gmail.com",
    "about_purpose":    "Enables Discord's connection path; you decide when to open Discord.",

    "update_title":     "Update",
    "update_check":     "Check for Updates",
    "update_available": "A new DPort version is available: v{version}\n\nCurrent version: v{current}\n\nDownload the setup file?",
    "update_current":   "DPort is already up to date.\n\nCurrent version: v{version}",
    "update_no_asset":  "v{version} is available but no setup file is attached.\n\nOpen GitHub Releases?",
    "update_downloaded":"The update was downloaded.\n\nStart setup and close DPort?",
    "update_failed":    "Update check could not be completed.",
    "update_verify_failed": "The downloaded update could not be verified; it was not run for safety.",
    "update_staging_failed": "A protected download folder for the update could not be prepared.\n\nFor safety the update is never downloaded into a folder a standard user can modify. You can install it manually from the GitHub Releases page.",
    "st_update_checking":"Checking for updates...",
    "st_update_downloading":"Downloading update...",

    "tip_about":        "About",
    "tip_help":         "Help / Troubleshooting",
    "tip_log":          "Show Log",
    "tip_settings":     "Settings",

    "help_title":       "Troubleshooting",
    "help_intro":       "If something goes wrong, try these in order:",
    "help_items": [
        ("Connection path won't enable / “port 443 busy”",
         "Another program may be using port 443 (XAMPP, IIS, another VPN/proxy). Close it and press “Enable Connection” again."),
        ("“Admin rights needed” warning",
         "Run DPort as administrator: right-click the shortcut → “Run as administrator”. It needs admin to write the hosts file."),
        ("“No secure DNS access”",
         "Check the computer's date and time. Temporarily disable HTTPS/encrypted-connection scanning in the antivirus and try again; otherwise use another network or a phone hotspot."),
        ("“No active network adapter”",
         "Your internet connection may be off. Make sure Wi-Fi or Ethernet is connected, then press “Enable Connection” again."),
        ("“Discord not found”",
         "Discord may not be installed, or it's in a different location. Download and install it from discord.com, then try again."),
        ("Discord still won't open",
         "First press “Enable Connection” in DPort, then open Discord from its own shortcut. If it persists, fully close Discord including the tray and try again."),
        ("Discord or discord.com won't open at all",
         "Happens if you force-killed DPort. Fix: reopen DPort (it auto-heals on start) or press “Restore Defaults”. Worst case, restart the PC — the installed safety task cleans it up."),
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
