"""Produtores de leituras de RSSI.

- AirodumpScanner: envolve o airodump-ng, que escreve CSV a cada segundo, e
  faz o parse da seção de APs (BSSID, canal, potência, ESSID).
- SimScanner: gera APs sintéticos com posições fixas e RSSI derivado do modelo
  de path loss + ruído gaussiano. Permite exercitar toda a pipeline/UI sem
  hardware (ou com placas que não suportam monitor mode).

Ambos expõem a mesma interface: start(), poll() -> list[reading], stop().
Cada reading: {bssid, ssid, channel, band, freq, rssi}.
"""

import csv
import glob
import math
import os
import random
import shutil
import subprocess
import tempfile


def channel_to_band(ch) -> str | None:
    try:
        ch = int(ch)
    except (TypeError, ValueError):
        return None
    if 1 <= ch <= 14:
        return "2.4"
    if 32 <= ch <= 177:
        return "5"
    return "6"


BAND_FLAG = {"2.4": "bg", "5": "a", "6": "6", "all": "abg"}


class BaseScanner:
    kind = "base"

    def start(self):  # pragma: no cover - interface
        ...

    def poll(self) -> list[dict]:  # pragma: no cover - interface
        return []

    def stop(self):  # pragma: no cover - interface
        ...


class AirodumpScanner(BaseScanner):
    kind = "real"

    def __init__(self, iface: str, band: str = "all", bssid: str | None = None,
                 channel: int | None = None):
        self.iface = iface
        self.band = band
        self.bssid = bssid
        self.channel = channel
        self.proc: subprocess.Popen | None = None
        self.tmp: str | None = None
        self.prefix: str | None = None

    def start(self):
        self.tmp = tempfile.mkdtemp(prefix="radar_")
        self.prefix = os.path.join(self.tmp, "scan")
        cmd = ["airodump-ng", "--write-interval", "1",
               "--output-format", "csv", "-w", self.prefix]
        if self.bssid:
            cmd += ["--bssid", self.bssid]
            if self.channel:
                cmd += ["-c", str(self.channel)]
        else:
            cmd += ["--band", BAND_FLAG.get(self.band, "abg")]
        cmd.append(self.iface)
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def poll(self) -> list[dict]:
        if self.proc and self.proc.poll() is not None:
            raise RuntimeError(
                "airodump-ng encerrou inesperadamente (interface em monitor mode?)"
            )
        files = sorted(glob.glob(f"{self.prefix}-*.csv"))
        if not files:
            return []
        return self._parse(files[-1])

    @staticmethod
    def _parse(path: str) -> list[dict]:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except FileNotFoundError:
            return []
        # A seção de APs vem antes da seção de Stations (separadas por linha em branco)
        sep = "\r\n\r\n" if "\r\n\r\n" in content else "\n\n"
        ap_block = content.split(sep)[0]

        rows = []
        header_seen = False
        for row in csv.reader(ap_block.splitlines()):
            if not row:
                continue
            first = row[0].strip()
            if first == "BSSID":
                header_seen = True
                continue
            if not header_seen or len(row) < 14:
                continue
            bssid = first
            if not bssid or ":" not in bssid:
                continue
            try:
                ch = int(row[3].strip())
            except ValueError:
                ch = None
            try:
                power = float(row[8].strip())
            except ValueError:
                continue
            if power >= 0:  # airodump usa -1/0 quando não mediu potência
                continue
            rows.append({
                "bssid": bssid.upper(),
                "ssid": row[13].strip(),
                "channel": ch,
                "band": channel_to_band(ch),
                "freq": None,
                "rssi": power,
            })
        return rows

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self.tmp and os.path.isdir(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)


class SimScanner(BaseScanner):
    kind = "sim"

    CH_BY_BAND = {"2.4": [1, 6, 11], "5": [36, 44, 149, 157], "6": [37, 53, 117]}
    VENDORS = ["NETGEAR", "TP-LINK_", "VIVO-", "CLARO_", "HackLab-",
               "AP-Recon", "Linksys", "GVT-", "AndroidAP", "iPhone"]

    def __init__(self, band: str = "all", n_aps: int = 9, a: float = -40.0,
                 n: float = 2.7, bssid: str | None = None):
        self.band = band
        self.a = a
        self.n = n
        self.bssid = bssid
        self.n_aps = n_aps
        self.aps: list[dict] = []

    def start(self):
        bands = ["2.4", "5", "6"] if self.band == "all" else [self.band]
        self.aps = []
        for _ in range(self.n_aps):
            band = random.choice(bands)
            ch = random.choice(self.CH_BY_BAND[band])
            mac = "%02X:%02X:%02X:%02X:%02X:%02X" % tuple(
                random.randint(0, 255) for _ in range(6)
            )
            self.aps.append({
                "bssid": mac,
                "ssid": random.choice(self.VENDORS) + str(random.randint(10, 99)),
                "channel": ch,
                "band": band,
                "true_dist": random.uniform(2, 70),
            })

    def poll(self) -> list[dict]:
        out = []
        for ap in self.aps:
            if self.bssid and ap["bssid"] != self.bssid.upper():
                continue
            d = ap["true_dist"] * random.uniform(0.92, 1.08)
            rssi = self.a - 10 * self.n * math.log10(max(d, 0.5)) + random.gauss(0, 2.5)
            out.append({
                "bssid": ap["bssid"],
                "ssid": ap["ssid"],
                "channel": ap["channel"],
                "band": ap["band"],
                "freq": None,
                "rssi": round(rssi, 1),
            })
        return out

    def stop(self):
        self.aps = []
