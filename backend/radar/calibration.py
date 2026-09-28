"""Motor de calibração RSSI -> distância.

Ajusta o modelo log-distance a amostras (distância_real, rssi) via mínimos
quadrados na forma linearizada:

    RSSI = A - 10*n*log10(d)

Estima A (intercepto) e n (a partir da inclinação) e o R² do ajuste.
Perfis são persistidos por BSSID em disco (JSON).
"""

import json
import math
import os
import threading


def fit(samples: list[list[float]]) -> dict | None:
    """samples: lista de [distancia_m, rssi]. Retorna {a, n, r2, samples} ou None."""
    pts = []
    for s in samples:
        try:
            d, r = float(s[0]), float(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        if d > 0:
            pts.append((d, r))
    if len(pts) < 2:
        return None

    xs = [math.log10(d) for d, _ in pts]
    ys = [r for _, r in pts]
    n_pts = len(pts)
    mx = sum(xs) / n_pts
    my = sum(ys) / n_pts
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return None
    slope = sxy / sxx           # = -10n
    intercept = my - slope * mx  # = A

    n = -slope / 10.0
    a = intercept
    # R²
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "a": round(a, 2),
        "n": round(n, 3),
        "r2": round(r2, 4),
        "samples": n_pts,
    }


def quality_note(profile: dict) -> str:
    """Sugestão textual sobre a qualidade do ajuste."""
    r2 = profile.get("r2", 0)
    n = profile.get("n", 0)
    if profile.get("samples", 0) < 3:
        return "Poucas amostras — colete pelo menos 3-5 distâncias."
    if r2 < 0.6:
        return "Ajuste ruim (R² baixo) — recalibre com medições mais consistentes."
    if not (1.6 <= n <= 4.0):
        return "Expoente n fora do usual (1.6–4.0) — verifique as distâncias informadas."
    return "Calibração OK."


class CalibrationStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.profiles: dict[str, dict] = {}
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.profiles = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.profiles = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, indent=2)
            os.replace(tmp, self.path)

    def get(self, bssid: str) -> dict | None:
        return self.profiles.get(bssid.upper() if bssid else bssid)

    def set(self, bssid: str, profile: dict):
        self.profiles[bssid.upper()] = profile
        self.save()

    def delete(self, bssid: str):
        self.profiles.pop(bssid.upper(), None)
        self.save()
