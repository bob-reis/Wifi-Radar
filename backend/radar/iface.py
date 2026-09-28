"""Configuração da interface wireless: monitor mode, domínio regulatório,
TX power e diagnóstico de driver. Wrappers finos sobre iw / airmon-ng / ip /
ethtool. Todas as chamadas são defensivas: em ambiente sem hardware ou sem
privilégio, retornam (False, motivo) em vez de estourar.
"""

import glob
import os
import re
import subprocess


def _run(cmd: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except FileNotFoundError:
        return False, f"comando não encontrado: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"timeout: {' '.join(cmd)}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def list_wifi_interfaces() -> list[str]:
    ifaces = set()
    for path in glob.glob("/sys/class/net/*/wireless"):
        ifaces.add(path.split("/")[-2])
    # Interfaces em monitor mode podem não ter /wireless; tenta via iw
    ok, out = _run(["iw", "dev"])
    if ok:
        for m in re.finditer(r"Interface (\S+)", out):
            ifaces.add(m.group(1))
    return sorted(ifaces)


def uplink_interfaces() -> set[str]:
    """Interfaces que carregam a rota default do host (conectividade/SSH).

    Colocar uma delas em monitor mode derruba a rede do host — o tool bloqueia
    isso. Retorna o conjunto de nomes de interface das rotas default (v4 e v6)."""
    ifs = set()
    for args in (["ip", "route", "show", "default"],
                 ["ip", "-6", "route", "show", "default"]):
        ok, out = _run(args)
        if ok:
            for m in re.finditer(r"dev (\S+)", out):
                ifs.add(m.group(1))
    return ifs


def interface_info(iface: str, uplinks: set[str] | None = None) -> dict:
    ok, out = _run(["iw", "dev", iface, "info"])
    mode = None
    if ok:
        m = re.search(r"type (\w+)", out)
        if m:
            mode = m.group(1)
    if uplinks is None:
        uplinks = uplink_interfaces()
    return {
        "iface": iface,
        "mode": mode,
        "monitor_capable": monitor_capable(iface),
        "uplink": iface in uplinks,
    }


def _phy_for(iface: str) -> str | None:
    try:
        with open(f"/sys/class/net/{iface}/phy80211/name") as f:
            return f.read().strip()
    except OSError:
        return None


def monitor_capable(iface: str) -> bool:
    """Checa se o phy da interface anuncia suporte a monitor mode."""
    phy = _phy_for(iface)
    if not phy:
        return False
    ok, out = _run(["iw", "phy", phy, "info"])
    if not ok:
        return False
    block = re.search(r"Supported interface modes:(.*?)(?:\n\s*\w|\Z)", out, re.S)
    if not block:
        return False
    return "monitor" in block.group(1).lower()


def enable_monitor(iface: str, kill_all: bool = False) -> tuple[bool, str]:
    """Ativa monitor mode SÓ na interface indicada, de forma cirúrgica.

    Importante: NÃO usa `airmon-ng check kill` por padrão, pois ele encerra o
    NetworkManager/wpa_supplicant globalmente — o que derruba a conectividade
    do host (inclusive a interface usada por SSH). Em vez disso:
      1. pede ao NetworkManager para NÃO gerenciar esta interface (nmcli);
      2. mata apenas o wpa_supplicant amarrado a ela, se houver;
      3. coloca a interface em monitor mode via `iw` (sem renomear);
      4. fallback para `airmon-ng start <iface>` (sem check kill).

    kill_all=True restaura o comportamento agressivo (mata NM global) — use
    só quando o host não depende de WiFi para rede.
    Retorna (ok, nome_da_interface_monitor).
    """
    if kill_all:
        _run(["airmon-ng", "check", "kill"])
    else:
        # Tira apenas esta interface do controle do NetworkManager
        _run(["nmcli", "device", "set", iface, "managed", "no"])
        _run(["pkill", "-f", f"wpa_supplicant.*{iface}"])

    # Caminho principal: iw manual, mantém o nome da interface
    _run(["ip", "link", "set", iface, "down"])
    ok1, out1 = _run(["iw", "dev", iface, "set", "monitor", "control"])
    if not ok1:
        _run(["iw", "dev", iface, "set", "type", "monitor"])
    _run(["ip", "link", "set", iface, "up"])
    if interface_info(iface).get("mode") == "monitor":
        return True, iface

    # Fallback: airmon-ng start (cria <iface>mon; ainda sem matar NM global)
    before = set(os.listdir("/sys/class/net")) if os.path.isdir("/sys/class/net") else set()
    ok, out = _run(["airmon-ng", "start", iface])
    after = set(os.listdir("/sys/class/net")) if os.path.isdir("/sys/class/net") else set()
    new = list(after - before)
    if new:
        _run(["nmcli", "device", "set", new[0], "managed", "no"])
        return True, new[0]
    if interface_info(iface).get("mode") == "monitor":
        return True, iface
    return False, out1 or out or "não foi possível ativar monitor mode"


def disable_monitor(iface: str) -> tuple[bool, str]:
    # Volta para managed via iw (não usa airmon-ng stop para não mexer no host)
    _run(["ip", "link", "set", iface, "down"])
    ok, out = _run(["iw", "dev", iface, "set", "type", "managed"])
    _run(["ip", "link", "set", iface, "up"])
    # Devolve a interface (e um eventual <iface>mon) ao NetworkManager
    base = iface[:-3] if iface.endswith("mon") else iface
    _run(["nmcli", "device", "set", base, "managed", "yes"])
    return ok, out


def set_regulatory(country: str) -> tuple[bool, str]:
    return _run(["iw", "reg", "set", country.upper()])


def get_regulatory() -> str:
    ok, out = _run(["iw", "reg", "get"])
    if ok:
        m = re.search(r"country (\w+)", out)
        if m:
            return m.group(1)
    return "?"


def set_txpower(iface: str, dbm: float) -> tuple[bool, str]:
    mbm = int(float(dbm) * 100)  # iw usa mBm (milibel-milliwatts)
    _run(["ip", "link", "set", iface, "up"])
    return _run(["iw", "dev", iface, "set", "txpower", "fixed", str(mbm)])


def driver_info(iface: str) -> dict:
    ok, out = _run(["ethtool", "-i", iface])
    info = {}
    if ok:
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip()] = v.strip()
    return {"ok": ok, "info": info, "raw": out}
