"""
Locale-independent DNS snapshots and verified restoration.
Registry access is read-only; netsh is the only mutation boundary.
"""
import base64
import ipaddress
import json
import subprocess
from typing import Dict, Optional, Tuple


class DnsSnapshotError(ValueError):
    pass


def normalize_snapshot(snapshot):
    """Validate all families before writes; accept legacy primary/secondary."""
    if not isinstance(snapshot, dict):
        raise DnsSnapshotError("DNS yedegi gecersiz")
    clean = {}
    for family, version in (("ipv4", 4), ("ipv6", 6)):
        data = snapshot.get(family)
        if not isinstance(data, dict) or type(data.get("dhcp")) is not bool:
            raise DnsSnapshotError(f"{family}: DNS kaynagi bilinmiyor")
        addresses = data.get("servers")
        if addresses is None:
            addresses = [data[k] for k in ("primary", "secondary") if data.get(k)]
        if not isinstance(addresses, list):
            raise DnsSnapshotError(f"{family}: DNS listesi gecersiz")
        servers = []
        for address in addresses:
            if not isinstance(address, str):
                raise DnsSnapshotError(f"{family}: DNS adresi gecersiz")
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise DnsSnapshotError(f"{family}: DNS adresi gecersiz") from exc
            if ip.version != version:
                raise DnsSnapshotError(f"{family}: DNS adres ailesi uyusmuyor")
            servers.append(str(ip))
        if not data["dhcp"] and not servers:
            raise DnsSnapshotError(f"{family}: statik DNS listesi bos")
        clean[family] = {
            "dhcp": data["dhcp"], "servers": servers,
            "primary": servers[0] if servers else None,
            "secondary": servers[1] if len(servers) > 1 else None,
        }
    if "interface_guid" in snapshot:
        import uuid
        try:
            clean["interface_guid"] = str(uuid.UUID(snapshot["interface_guid"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise DnsSnapshotError("Adaptor kimligi gecersiz") from exc
    return clean


def get_dns(adapter_name: str) -> Dict:
    """Read effective DNS via CIM and static source via per-interface NameServer.

    Missing/inaccessible registry keys fail closed. Only a successfully opened
    key with absent/empty NameServer means automatic. No registry writes.
    """
    encoded = base64.b64encode(adapter_name.encode("utf-8")).decode("ascii")
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$alias = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__ALIAS__'))
$adapters = @(Get-NetAdapter -IncludeHidden | Where-Object { $_.Name -ceq $alias })
if ($adapters.Count -ne 1) { throw 'Adapter not uniquely resolved' }
$adapter = $adapters[0]
$guid = ([guid]$adapter.InterfaceGuid).ToString()
$result = @{interface_guid=$guid}
foreach ($family in @(@('ipv4','Tcpip','IPv4'), @('ipv6','Tcpip6','IPv6'))) {
    $path = 'SYSTEM\CurrentControlSet\Services\' + $family[1] + '\Parameters\Interfaces\{' + $guid + '}'
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($path, $false)
    if ($null -eq $key) { throw 'DNS registry key unavailable' }
    try {
        $raw = $key.GetValue('NameServer', '')
        if ($raw -isnot [string]) { throw 'Invalid NameServer type' }
        $static = @($raw -split '[,;\s]+' | Where-Object { $_ })
    } finally { $key.Dispose() }
    $rows = @(Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -AddressFamily $family[2])
    if ($rows.Count -ne 1) { throw 'DNS family unavailable' }
    $result[$family[0]] = @{dhcp=($static.Count -eq 0); servers=$static; effective=@($rows[0].ServerAddresses)}
}
$result | ConvertTo-Json -Depth 5 -Compress
""".replace("__ALIAS__", encoded)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="strict",
            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise DnsSnapshotError("Windows DNS sorgusu basarisiz")
        raw = json.loads(result.stdout.lstrip("\ufeff"))
        clean = normalize_snapshot(raw)
        for family in ("ipv4", "ipv6"):
            effective = raw[family].get("effective")
            if not isinstance(effective, list):
                raise DnsSnapshotError("Etkin DNS listesi okunamadi")
            effective = [str(ipaddress.ip_address(ip)) for ip in effective]
            # Effective servers may be empty when IPv6 binding is disabled.
            # Restore the configured source/list, not transient operational state.
        return clean
    except DnsSnapshotError:
        raise
    except Exception as exc:
        raise DnsSnapshotError("DNS durumu guvenle okunamadi") from exc

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
            errors.append(f"IPv6 birincil: {(r.stderr or r.stdout).strip()}")

        # --- IPv6 secondary ---
        if ipv6_secondary:
            r = subprocess.run(
                ["netsh", "interface", "ipv6", "add", "dnsservers",
                 adapter_name, ipv6_secondary, "index=2", "validate=no"],
                capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if r.returncode != 0:
                errors.append(f"IPv6 ikincil: {(r.stderr or r.stdout).strip()}")

    if errors:
        return False, "\n".join(errors)
    return True, "OK"


def restore_dns(adapter_name: str, snapshot: Dict) -> Tuple[bool, str]:
    """Restore all ordered servers; success requires verified read-back."""
    try:
        wanted = normalize_snapshot(snapshot)
        if wanted.get("interface_guid"):
            current = get_dns(adapter_name)
            if current.get("interface_guid") != wanted["interface_guid"]:
                raise DnsSnapshotError("Adaptor kimligi degisti")
    except Exception as exc:
        return False, str(exc)
    errors = []
    for family in ("ipv4", "ipv6"):
        data = wanted[family]
        prefix = ["netsh", "interface", family]
        if data["dhcp"]:
            commands = [prefix + ["set", "dnsservers", adapter_name, "dhcp"]]
        else:
            commands = [prefix + ["set", "dnsservers", adapter_name,
                                  "static", data["servers"][0], "validate=no"]]
            for index, address in enumerate(data["servers"][1:], 2):
                commands.append(prefix + ["add", "dnsservers", adapter_name,
                                         address, f"index={index}", "validate=no"])
        for command in commands:
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=12,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode:
                    errors.append(f"{family}: {(result.stderr or result.stdout).strip()}")
                    break
            except Exception as exc:
                errors.append(f"{family}: {exc}")
                break
    if not errors:
        try:
            actual = normalize_snapshot(get_dns(adapter_name))
            for family in ("ipv4", "ipv6"):
                expected = wanted[family]
                observed = actual[family]
                if expected["dhcp"] != observed["dhcp"] or (
                    not expected["dhcp"] and expected["servers"] != observed["servers"]
                ):
                    errors.append(f"{family}: geri yukleme dogrulanamadi")
            if wanted.get("interface_guid") and actual.get("interface_guid") != wanted["interface_guid"]:
                errors.append("Adaptor kimligi degisti")
        except Exception as exc:
            errors.append(f"DNS geri okuma basarisiz: {exc}")
    return (False, "\n".join(errors)) if errors else (True, "OK")


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
