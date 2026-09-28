"""Estado do radar: mantém os APs vistos, os filtros de Kalman por BSSID e a
configuração ativa. Aplica filtragem + estimativa de distância a cada rodada
de leituras e produz um snapshot serializável para o frontend.
"""

import time

from .calibration import CalibrationStore
from .distance import DEFAULT_A, ENV_N, estimate_distance
from .kalman import KalmanRSSI

STALE_AFTER = 30.0  # segundos sem ver o AP -> removido do snapshot


class RadarState:
    def __init__(self, calib: CalibrationStore):
        self.calib = calib
        self.config = {
            "environment": "urban",
            "a": DEFAULT_A,
            "n": ENV_N["urban"],
            "band": "all",
        }
        self.aps: dict[str, dict] = {}
        self.filters: dict[str, KalmanRSSI] = {}
        self.focus: str | None = None

    def set_environment(self, env: str):
        self.config["environment"] = env
        self.config["n"] = ENV_N.get(env, ENV_N["urban"])

    def reset(self):
        self.aps.clear()
        self.filters.clear()

    def _distance_for(self, bssid: str, rssi: float):
        prof = self.calib.get(bssid)
        if prof:
            return estimate_distance(rssi, prof["a"], prof["n"]), True
        return estimate_distance(rssi, self.config["a"], self.config["n"]), False

    def update(self, readings: list[dict]) -> dict:
        now = time.time()
        for r in readings:
            bssid = r["bssid"]
            raw = r["rssi"]
            if raw is None:
                continue
            f = self.filters.get(bssid)
            if f is None:
                f = self.filters[bssid] = KalmanRSSI(initial=raw)
                filt = raw
            else:
                filt = f.update(raw)
            dist, calibrated = self._distance_for(bssid, filt)
            ap = self.aps.get(bssid, {"bssid": bssid, "first_seen": now})
            ap.update({
                "ssid": r.get("ssid") or ap.get("ssid") or "",
                "channel": r.get("channel"),
                "band": r.get("band"),
                "freq": r.get("freq"),
                "rssi_raw": round(raw, 1),
                "rssi": round(filt, 1),
                "distance": dist,
                "calibrated": calibrated,
                "last_seen": now,
            })
            self.aps[bssid] = ap
        return self.snapshot()

    def snapshot(self) -> dict:
        now = time.time()
        aps = []
        for bssid, ap in list(self.aps.items()):
            age = now - ap["last_seen"]
            if age > STALE_AFTER:
                del self.aps[bssid]
                continue
            item = dict(ap)
            item["age"] = round(age, 1)
            aps.append(item)
        aps.sort(key=lambda x: (x["distance"] is None, x["distance"] or 9e9))
        return {
            "aps": aps,
            "config": self.config,
            "focus": self.focus,
            "ts": now,
        }
