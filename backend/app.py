"""Hackers-Arise Wi-Fi Radar — versão web (FastAPI + WebSocket).

Reescreve o núcleo do tool de terminal como serviço web: orquestra o scan
(airodump-ng ou simulação), aplica Kalman + estimativa de distância e faz
stream do estado ao vivo via WebSocket. Serve também a UI estática.
"""

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.radar import iface as ifacemod
from backend.radar.calibration import CalibrationStore, fit, quality_note
from backend.radar.distance import ENV_N
from backend.radar.scanner import AirodumpScanner, SimScanner
from backend.radar.state import RadarState

BASE = Path(__file__).resolve().parent.parent
FRONTEND = BASE / "frontend"
DATA = Path(os.environ.get("RADAR_DATA", str(BASE / "data")))
DATA.mkdir(parents=True, exist_ok=True)

calib = CalibrationStore(str(DATA / "calibration.json"))
state = RadarState(calib)


class ScanManager:
    def __init__(self):
        self.scanner = None
        self.task: asyncio.Task | None = None
        self.clients: set[WebSocket] = set()
        self.running = False
        self.interval = 1.0
        self.mode: str | None = None
        self.mon_iface: str | None = None
        self.error: str | None = None

    async def broadcast(self, msg: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _loop(self):
        while self.running:
            try:
                readings = await asyncio.to_thread(self.scanner.poll)
                snap = state.update(readings)
                snap.update({"running": True, "mode": self.mode,
                             "monitor": self.mon_iface})
                await self.broadcast({"type": "scan", "data": snap})
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                self.running = False
                await self.broadcast({"type": "error", "message": str(e)})
                break
            await asyncio.sleep(self.interval)

    async def start(self, cfg: dict):
        await self.stop()
        self.error = None
        state.reset()
        mode = cfg.get("mode", "real")
        band = cfg.get("band", "all")
        bssid = cfg.get("bssid")
        channel = cfg.get("channel")
        state.set_environment(cfg.get("environment", "urban"))
        state.focus = bssid
        self.mode = mode

        if mode == "sim":
            self.scanner = SimScanner(
                band=band, a=state.config["a"], n=state.config["n"], bssid=bssid,
            )
            self.mon_iface = "sim0"
        else:
            iface = cfg.get("interface")
            if not iface:
                raise RuntimeError("Nenhuma interface selecionada.")
            if not cfg.get("force") and iface in ifacemod.uplink_interfaces():
                raise RuntimeError(
                    f"A interface '{iface}' provê a conectividade do host "
                    f"(rota default). Colocá-la em monitor mode derrubaria a "
                    f"rede e o SSH. Use um adaptador USB dedicado."
                )
            ok, mon = ifacemod.enable_monitor(iface)
            if not ok:
                raise RuntimeError(
                    f"Falha ao ativar monitor mode em {iface}: {mon}"
                )
            self.mon_iface = mon
            if cfg.get("country"):
                ifacemod.set_regulatory(cfg["country"])
            if cfg.get("txpower") is not None:
                ifacemod.set_txpower(mon, cfg["txpower"])
            self.scanner = AirodumpScanner(
                mon, band=band, bssid=bssid, channel=channel,
            )

        await asyncio.to_thread(self.scanner.start)
        self.running = True
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        if self.scanner:
            await asyncio.to_thread(self.scanner.stop)
            self.scanner = None


mgr = ScanManager()
app = FastAPI(title="Hackers-Arise Wi-Fi Radar (Web)")


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND / "index.html"))


@app.get("/api/interfaces")
async def interfaces():
    uplinks = ifacemod.uplink_interfaces()
    ifs = [ifacemod.interface_info(i, uplinks)
           for i in ifacemod.list_wifi_interfaces()]
    return {
        "interfaces": ifs,
        "environments": list(ENV_N.keys()),
        "regulatory": ifacemod.get_regulatory(),
        "uplinks": sorted(uplinks),
    }


class StartCfg(BaseModel):
    mode: str = "real"
    interface: str | None = None
    band: str = "all"
    environment: str = "urban"
    country: str | None = None
    txpower: float | None = None
    bssid: str | None = None
    channel: int | None = None
    force: bool = False  # permite escanear pela interface de uplink (perigoso)


@app.post("/api/scan/start")
async def scan_start(cfg: StartCfg):
    try:
        await mgr.start(cfg.model_dump())
        return {"ok": True, "mode": mgr.mode, "monitor": mgr.mon_iface}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/api/scan/stop")
async def scan_stop():
    # Apenas encerra o scanner (mata o airodump-ng). NÃO mexe na interface:
    # não tira do monitor mode nem devolve ao NetworkManager — isso fica a
    # cargo do usuário / de uma ação explícita.
    await mgr.stop()
    state.reset()  # limpa os APs para o radar parar visivelmente na hora
    await mgr.broadcast({
        "type": "scan",
        "data": {**state.snapshot(), "running": False, "mode": None,
                 "monitor": None},
    })
    return {"ok": True, "running": False}


@app.get("/api/status")
async def status():
    return {
        "running": mgr.running,
        "mode": mgr.mode,
        "monitor": mgr.mon_iface,
        "error": mgr.error,
        "clients": len(mgr.clients),
    }


@app.get("/api/calibration")
async def get_calibration():
    return {
        b: {**p, "note": quality_note(p)} for b, p in calib.profiles.items()
    }


class CalibReq(BaseModel):
    bssid: str
    samples: list[list[float]]


@app.post("/api/calibration")
async def post_calibration(req: CalibReq):
    res = fit(req.samples)
    if not res:
        return JSONResponse(
            status_code=400,
            content={"error": "Informe ao menos 2 amostras com distância > 0."},
        )
    calib.set(req.bssid, res)
    return {"ok": True, "profile": {**res, "note": quality_note(res)}}


@app.delete("/api/calibration/{bssid}")
async def delete_calibration(bssid: str):
    calib.delete(bssid)
    return {"ok": True}


class TuneReq(BaseModel):
    interface: str | None = None
    country: str | None = None
    txpower: float | None = None


@app.post("/api/tune")
async def tune(req: TuneReq):
    out = {}
    if req.country:
        ok, msg = ifacemod.set_regulatory(req.country)
        out["regulatory"] = {"ok": ok, "msg": msg}
    if req.interface and req.txpower is not None:
        ok, msg = ifacemod.set_txpower(req.interface, req.txpower)
        out["txpower"] = {"ok": ok, "msg": msg}
    if req.interface:
        out["driver"] = ifacemod.driver_info(req.interface)
    out["current_reg"] = ifacemod.get_regulatory()
    return out


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    mgr.clients.add(websocket)
    await websocket.send_json({
        "type": "scan",
        "data": {**state.snapshot(), "running": mgr.running, "mode": mgr.mode,
                 "monitor": mgr.mon_iface},
    })
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        mgr.clients.discard(websocket)
    except Exception:  # noqa: BLE001
        mgr.clients.discard(websocket)


# Estáticos (JS/CSS) — montado por último para não capturar as rotas de API.
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
