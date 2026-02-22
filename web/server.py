"""
FastAPI web server for NEV GCS.

Endpoints:
  GET  /                      → index.html
  GET  /api/state             → current state snapshot (JSON)
  POST /api/cmd_mode          → send mode change to vehicle
  POST /api/estop             → send e-stop command to vehicle
  WS   /ws                    → real-time state push
  WS   /ws/vehicle            → vehicle JPEG frame ingress
  POST /api/webrtc/offer      → WebRTC SDP offer/answer (browser ↔ GCS)
"""
import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import video_relay

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / 'static'


def create_app(state, proto):
    app = FastAPI(title='NEV GCS', docs_url=None, redoc_url=None)

    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return (STATIC_DIR / 'index.html').read_text()

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------

    class CmdModeReq(BaseModel):
        mode: int

    class EStopReq(BaseModel):
        active: bool

    @app.get('/api/state')
    async def get_state():
        return json.loads(state.to_json())

    @app.post('/api/cmd_mode')
    async def set_cmd_mode(req: CmdModeReq):
        if req.mode not in (-1, 0, 1, 2):
            return {'ok': False, 'error': f'invalid mode: {req.mode}'}
        state.control.mode = req.mode
        proto.send_cmd_mode(req.mode)
        logger.info(f'Mode → {req.mode}')
        return {'ok': True, 'mode': req.mode}

    @app.post('/api/estop')
    async def set_estop(req: EStopReq):
        state.control.estop = req.active
        proto.send_estop(req.active)
        logger.info(f'E-stop → {req.active}')
        return {'ok': True, 'active': req.active}

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    @app.websocket('/ws')
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        state.add_subscriber(queue)
        logger.info(f'WebSocket client connected: {ws.client}')

        try:
            # Immediately push current state
            await ws.send_text(state.to_json())

            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=5.0)
                    await ws.send_text(data)
                except asyncio.TimeoutError:
                    # Keepalive: push current state
                    await ws.send_text(state.to_json())
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            state.remove_subscriber(queue)
            logger.info(f'WebSocket client disconnected: {ws.client}')

    # ------------------------------------------------------------------
    # Video: vehicle → GCS (JPEG frames over WebSocket)
    # ------------------------------------------------------------------

    @app.websocket('/ws/vehicle')
    async def vehicle_video_ws(ws: WebSocket):
        await ws.accept()
        logger.info(f'Vehicle video WebSocket connected: {ws.client}')
        try:
            while True:
                data = await ws.receive_bytes()
                await video_relay.handle_vehicle_frame(data)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning(f'Vehicle video WebSocket error: {exc}')
        finally:
            logger.info(f'Vehicle video WebSocket disconnected: {ws.client}')

    # ------------------------------------------------------------------
    # Video: GCS → browser (WebRTC signaling)
    # ------------------------------------------------------------------

    @app.post('/api/webrtc/offer')
    async def webrtc_offer(request: Request):
        params = await request.json()
        return await video_relay.handle_webrtc_offer(params['sdp'], params['type'])

    return app
