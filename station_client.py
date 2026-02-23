"""
Station client — nev_gcs (스테이션) 측 Zenoh 클라이언트.

서버의 zenohd에 연결하여 nev/station/* 토픽을 발행.

토픽:
  nev/station/heartbeat          → 서버 keepalive (5 Hz)
  nev/station/teleop             → 조이스틱 명령 (20 Hz)
  nev/station/estop              → E-Stop (이벤트)
  nev/station/cmd_mode           → 모드 변경 (이벤트)
  nev/station/joystick_connected → 조이스틱 연결 여부 (이벤트)
"""
import asyncio
import json
import logging
import time

import zenoh

logger = logging.getLogger(__name__)


class StationClient:
    def __init__(self):
        self._session = None
        self._pubs: dict = {}
        self._seq = 0

    def start(self, locator: str = '') -> None:
        conf = zenoh.Config()
        if locator:
            conf.insert_json5('connect/endpoints', json.dumps([locator]))
        self._session = zenoh.open(conf)

        for key in ('nev/station/heartbeat',
                    'nev/station/teleop',
                    'nev/station/estop',
                    'nev/station/cmd_mode',
                    'nev/station/joystick_connected'):
            self._pubs[key] = self._session.declare_publisher(key)

        logger.info(f'StationClient started → {locator or "auto-discovery"}')

    def stop(self) -> None:
        for pub in self._pubs.values():
            pub.undeclare()
        if self._session:
            self._session.close()

    # ── Publish helpers ───────────────────────────────────────────────────────

    def _next_seq(self) -> int:
        s = self._seq
        self._seq = (self._seq + 1) % 65536
        return s

    def _zput(self, key: str, data: dict) -> None:
        try:
            self._pubs[key].put(json.dumps(data))
        except Exception as e:
            logger.warning(f'zenoh put [{key}]: {e}')

    def send_heartbeat(self):
        self._zput('nev/station/heartbeat', {'ts': time.time(), 'seq': self._next_seq()})

    def send_teleop(self, linear_x: float, angular_z: float):
        self._zput('nev/station/teleop', {
            'linear_x':  round(linear_x, 3),
            'angular_z': round(angular_z, 3),
            'seq':       self._next_seq(),
        })

    def send_estop(self, activate: bool):
        self._zput('nev/station/estop', {'active': activate, 'seq': self._next_seq()})
        logger.info(f'E-stop → {activate}')

    def send_cmd_mode(self, mode: int):
        self._zput('nev/station/cmd_mode', {'mode': mode, 'seq': self._next_seq()})
        logger.info(f'Cmd mode → {mode}')

    def send_joystick_connected(self, connected: bool):
        self._zput('nev/station/joystick_connected', {'connected': connected})


# ── Send loop (asyncio) ───────────────────────────────────────────────────────

async def run_send_loop(client: StationClient, state, cfg: dict):
    """
    heartbeat 5 Hz + teleop 20 Hz 발행.
    """
    hb_interval = 1.0 / cfg.get('heartbeat_rate', 5.0)
    tc_interval = 1.0 / cfg.get('teleop_rate',    20.0)

    last_hb = 0.0
    last_tc = 0.0

    while True:
        now = time.monotonic()

        if now - last_hb >= hb_interval:
            client.send_heartbeat()
            last_hb = now

        if now - last_tc >= tc_interval:
            client.send_teleop(state.linear_x, state.angular_z)
            last_tc = now

        await asyncio.sleep(0.01)
