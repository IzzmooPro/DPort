"""
core/adapter_manager.py
Ağ adaptörlerini listeler. 'netsh interface show interface' kullanır.
"""
import json
import subprocess
from typing import List, Dict


def get_all_adapters() -> List[Dict]:
    """
    Sistemdeki tüm ağ arayüzlerini döndürür.
    Her eleman: {'name', 'admin_state', 'state', 'type'}
    """
    adapters = _get_all_adapters_powershell()
    if adapters:
        return adapters
    return _get_all_adapters_netsh()


def _get_all_adapters_powershell() -> List[Dict]:
    """Get-NetAdapter nesne ciktisi dil bagimsiz oldugu icin once bunu dener."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Get-NetAdapter | Select-Object Name,Status,AdminStatus,InterfaceDescription | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        raw = json.loads(result.stdout)
        if isinstance(raw, dict):
            raw = [raw]

        adapters = []
        for item in raw:
            status = str(item.get("Status") or "")
            admin = str(item.get("AdminStatus") or "")
            status_l = status.lower()
            admin_l = admin.lower()
            enabled = admin_l in {"up", "1", "enabled"} or (not admin_l and status_l != "disabled")
            adapters.append(
                {
                    "name": item.get("Name") or "",
                    "admin_state": "Enabled" if enabled else "Disabled",
                    "state": "Connected" if status_l == "up" else status or "Disconnected",
                    "type": item.get("InterfaceDescription") or "",
                }
            )
        return [a for a in adapters if a["name"]]
    except Exception as e:
        print(f"[AdapterManager] PowerShell hatasi: {e}")
        return []


def _get_all_adapters_netsh() -> List[Dict]:
    try:
        result = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        lines = result.stdout.splitlines()

        # Başlık satırını bul
        header_idx = -1
        header_line = ""
        for i, line in enumerate(lines):
            if "Admin State" in line and "Interface Name" in line:
                header_idx = i
                header_line = line
                break

        if header_idx == -1:
            return []

        # Sütun başlangıç pozisyonları
        admin_pos = header_line.find("Admin State")
        after_admin = admin_pos + len("Admin State")
        state_pos = header_line.find("State", after_admin)
        type_pos = header_line.find("Type", state_pos)
        name_pos = header_line.find("Interface Name", type_pos)

        adapters = []
        # Başlık + ayırıcı satırı atla
        for line in lines[header_idx + 2 :]:
            if len(line) <= name_pos:
                continue
            admin = line[admin_pos:state_pos].strip()
            state = line[state_pos:type_pos].strip()
            itype = line[type_pos:name_pos].strip()
            name = line[name_pos:].strip()
            if name and admin and state:
                adapters.append(
                    {
                        "name": name,
                        "admin_state": admin,
                        "state": state,
                        "type": itype,
                    }
                )
        return adapters

    except Exception as e:
        print(f"[AdapterManager] netsh hatasi: {e}")
        return []


def get_active_adapters() -> List[Dict]:
    """
    Yalnızca Enabled + Connected adaptörleri döndürür.
    """
    return [
        a
        for a in get_all_adapters()
        if a.get("state") == "Connected" and a.get("admin_state") == "Enabled"
    ]
