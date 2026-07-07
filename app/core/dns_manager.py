"""
core/dns_manager.py
netsh üzerinden DNS okuma/yazma/sıfırlama işlemleri.
"""
import subprocess
import re
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# DNS Okuma
# ---------------------------------------------------------------------------

def get_dns(adapter_name: str) -> Dict:
    """
    Bir adaptörün mevcut DNS ayarlarını döndürür.
    Dönüş: {
        'ipv4': {'primary': str|None, 'secondary': str|None, 'dhcp': bool},
        'ipv6': {'primary': str|None, 'secondary': str|None, 'dhcp': bool}
    }
    """
    result = {
        "ipv4": {"primary": None, "secondary": None, "dhcp": True},
        "ipv6": {"primary": None, "secondary": None, "dhcp": True},
    }

    # IPv4
    try:
        r = subprocess.run(
            ["netsh", "interface", "ip", "show", "dnsservers", adapter_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        _parse_dns_output(r.stdout, result["ipv4"], ipv6=False)
    except Exception as e:
        print(f"[DNS] IPv4 okuma hatası ({adapter_name}): {e}")

    # IPv6
    try:
        r = subprocess.run(
            ["netsh", "interface", "ipv6", "show", "dnsservers", adapter_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        _parse_dns_output(r.stdout, result["ipv6"], ipv6=True)
    except Exception as e:
        print(f"[DNS] IPv6 okuma hatası ({adapter_name}): {e}")

    return result


def _parse_dns_output(output: str, dns_dict: dict, ipv6: bool = False):
    """netsh dnsservers çıktısını ayrıştırır."""
    ips: List[str] = []
    dhcp = True
    collecting = False  # "Servers configured…" satırından sonra IP topla

    for line in output.splitlines():
        lower = line.lower()

        # DHCP/Static belirleme
        if "dhcp" in lower and "server" in lower:
            dhcp = True
            collecting = True
        elif "statically" in lower:
            dhcp = False
            collecting = True
        elif collecting and line.strip() == "":
            collecting = False  # Boş satır → IP bölgesi bitti

        if not ipv6:
            found = re.findall(
                r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
                r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
                line,
            )
        else:
            # IPv6: en az iki grup, ':' içersin
            found = re.findall(
                r"(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}",
                line,
            )
            # Çok kısa veya sadece ':' içeren gürültüyü filtrele
            found = [ip for ip in found if len(ip) >= 5 and ip.count(":") >= 2]

        for ip in found:
            if ip not in ips:
                ips.append(ip)

    dns_dict["dhcp"] = dhcp
    dns_dict["primary"] = ips[0] if len(ips) > 0 else None
    dns_dict["secondary"] = ips[1] if len(ips) > 1 else None


# ---------------------------------------------------------------------------
# DNS Yazma
# ---------------------------------------------------------------------------

def set_dns(
    adapter_name: str,
    ipv4_primary: str,
    ipv4_secondary: Optional[str] = None,
    ipv6_primary: Optional[str] = None,
    ipv6_secondary: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verilen adaptöre DNS atar.
    Başarı: (True, "OK")
    Hata  : (False, hata_mesajı)
    """
    errors = []

    # --- IPv4 primary ---
    r = subprocess.run(
        ["netsh", "interface", "ip", "set", "dnsservers",
         adapter_name, "static", ipv4_primary],
        capture_output=True, text=True,
        encoding="utf-8", errors="ignore", timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    if r.returncode != 0:
        errors.append(f"IPv4 birincil: {(r.stderr or r.stdout).strip()}")

    # --- IPv4 secondary ---
    if ipv4_secondary:
        r = subprocess.run(
            ["netsh", "interface", "ip", "add", "dnsservers",
             adapter_name, ipv4_secondary, "index=2"],
            capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode != 0:
            errors.append(f"IPv4 ikincil: {(r.stderr or r.stdout).strip()}")

    # --- IPv6 primary ---
    if ipv6_primary:
        r = subprocess.run(
            ["netsh", "interface", "ipv6", "set", "dnsservers",
             adapter_name, "static", ipv6_primary, "validate=no"],
            capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode != 0:
            # IPv6 olmayabilir, kritik hata sayma
            print(f"[DNS] IPv6 birincil uyarı: {(r.stderr or r.stdout).strip()}")

        # --- IPv6 secondary ---
        if ipv6_secondary:
            subprocess.run(
                ["netsh", "interface", "ipv6", "add", "dnsservers",
                 adapter_name, ipv6_secondary, "index=2", "validate=no"],
                capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

    if errors:
        return False, "\n".join(errors)
    return True, "OK"


def restore_dns(adapter_name: str, snapshot: Dict) -> Tuple[bool, str]:
    """Adaptoru, `snapshot` (get_dns ciktisi) ile kaydedilmis ORIJINAL durumuna
    dondurur: onceden statik ise statik IP'leri, DHCP ise DHCP.

    reset_to_dhcp'ten farki: kullanicinin kendi ozel/statik DNS'ini korur,
    kaybettirmez."""
    v4 = snapshot.get("ipv4", {}) if snapshot else {}
    v6 = snapshot.get("ipv6", {}) if snapshot else {}
    errors = []

    # --- IPv4 ---
    if v4.get("dhcp", True) or not v4.get("primary"):
        r = subprocess.run(
            ["netsh", "interface", "ip", "set", "dnsservers", adapter_name, "dhcp"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            errors.append(f"IPv4 DHCP: {(r.stderr or r.stdout).strip()}")
    else:
        r = subprocess.run(
            ["netsh", "interface", "ip", "set", "dnsservers",
             adapter_name, "static", v4["primary"]],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            errors.append(f"IPv4 statik: {(r.stderr or r.stdout).strip()}")
        if v4.get("secondary"):
            subprocess.run(
                ["netsh", "interface", "ip", "add", "dnsservers",
                 adapter_name, v4["secondary"], "index=2"],
                capture_output=True, text=True, encoding="utf-8", errors="ignore",
                timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
            )

    # --- IPv6 (olmayabilir; hatalari kritik sayma) ---
    if v6.get("dhcp", True) or not v6.get("primary"):
        subprocess.run(
            ["netsh", "interface", "ipv6", "set", "dnsservers", adapter_name, "dhcp"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        subprocess.run(
            ["netsh", "interface", "ipv6", "set", "dnsservers",
             adapter_name, "static", v6["primary"], "validate=no"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if v6.get("secondary"):
            subprocess.run(
                ["netsh", "interface", "ipv6", "add", "dnsservers",
                 adapter_name, v6["secondary"], "index=2", "validate=no"],
                capture_output=True, text=True, encoding="utf-8", errors="ignore",
                timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
            )

    if errors:
        return False, "\n".join(errors)
    return True, "OK"


def reset_to_dhcp(adapter_name: str) -> Tuple[bool, str]:
    """
    Adaptörü otomatik DNS alacak şekilde sıfırlar (DHCP).
    """
    errors = []

    r = subprocess.run(
        ["netsh", "interface", "ip", "set", "dnsservers",
         adapter_name, "dhcp"],
        capture_output=True, text=True,
        encoding="utf-8", errors="ignore", timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    if r.returncode != 0:
        errors.append(f"IPv4 DHCP: {(r.stderr or r.stdout).strip()}")

    # IPv6 DHCP — IPv6 olmayabilir, hatayı görmezden gel
    subprocess.run(
        ["netsh", "interface", "ipv6", "set", "dnsservers",
         adapter_name, "dhcp"],
        capture_output=True, text=True,
        encoding="utf-8", errors="ignore", timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    if errors:
        return False, "\n".join(errors)
    return True, "OK"


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def get_current_provider_id(v4_primary: str, providers: list) -> Optional[str]:
    """
    Verilen IPv4 birincil adresini providers listesiyle karşılaştırır,
    eşleşen sağlayıcının id'sini döndürür.
    """
    if not v4_primary:
        return None

    for p in providers:
        if v4_primary in p.get("ipv4", []):
            return p["id"]
    return None
