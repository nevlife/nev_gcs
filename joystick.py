"""
Joystick input handler.

일반적인 게임패드 기준 축 배치:
  axis 0 : 왼쪽 스틱 X  ← raw_steer  표시용
  axis 1 : 왼쪽 스틱 Y  ← linear_x  제어
  axis 3 : 오른쪽 스틱 X ← steering_angle 제어 (→ angular_z 자리로 전송)
  axis 4 : 오른쪽 스틱 Y ← raw_speed 표시용

오른쪽 스틱 X → 조향각(rad) 변환 후 TC 패킷의 angular_z 자리로 전송.
max_steer_deg 로 최대 조향각 설정.

Config keys:
  axis_speed     : linear_x 축          (default 1, 왼쪽 스틱 Y)
  axis_steer     : 조향각 축            (default 3, 오른쪽 스틱 X)
  axis_raw_speed : raw_speed 표시 축    (default 4, 오른쪽 스틱 Y)
  axis_raw_steer : raw_steer 표시 축    (default 0, 왼쪽 스틱 X)
  btn_estop      : e-stop 토글 버튼     (default 4)
  max_speed      : 최대 속도 m/s        (default 1.0)
  max_steer_deg  : 최대 조향각 (도)     (default 27.0)
  deadzone       : 축 데드존            (default 0.05)
  invert_speed   : 속도 축 반전         (default True)
"""
import math
import time
import threading
import logging
from typing import Optional

from state import SharedState

logger = logging.getLogger(__name__)

try:
    import pygame
    _HAS_PYGAME = True
except ImportError:
    _HAS_PYGAME = False
    logger.warning('pygame not installed — joystick disabled')


class JoystickHandler:
    def __init__(self, state: SharedState, cfg: dict):
        self.state          = state
        self.axis_speed     = cfg.get('axis_speed',     1)   # 왼쪽 스틱 Y
        self.axis_steer     = cfg.get('axis_steer',     3)   # 오른쪽 스틱 X
        self.axis_raw_speed = cfg.get('axis_raw_speed', 4)   # 오른쪽 스틱 Y (표시용)
        self.axis_raw_steer = cfg.get('axis_raw_steer', 0)   # 왼쪽 스틱 X  (표시용)
        self.btn_estop      = cfg.get('btn_estop',      4)
        self.max_speed      = cfg.get('max_speed',      1.0)
        self.max_steer      = math.radians(cfg.get('max_steer_deg', 27.0))
        self.deadzone       = cfg.get('deadzone',       0.05)
        self.invert_speed   = cfg.get('invert_speed',   True)

        self._joystick: Optional[object] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._prev_btn_estop = False
        self._proto = None
        self._loop = None
        self._use_estop_btn  = False
        self._has_raw_speed  = False
        self._has_raw_steer  = False
        self._last_broadcast = 0.0

    def start(self):
        if not _HAS_PYGAME:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name='joystick', daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def set_proto(self, proto):
        self._proto = proto

    def set_loop(self, loop):
        self._loop = loop

    # ------------------------------------------------------------------

    def _run(self):
        pygame.init()
        pygame.joystick.init()

        while self._running:
            if self._joystick is None:
                self._try_connect()
                if self._joystick is None:
                    time.sleep(1.0)
                continue

            # event.pump() 실패 = 하드웨어 단절. 나머지 오류와 분리.
            try:
                pygame.event.pump()
            except pygame.error as e:
                logger.warning(f'Joystick disconnected: {e}')
                self._on_disconnect()
                continue

            if pygame.joystick.get_count() == 0:
                logger.warning('Joystick disconnected')
                self._on_disconnect()
                continue

            # 속도: 왼쪽 스틱 Y → linear_x (직접 매핑)
            speed_raw = self._apply_deadzone(self._joystick.get_axis(self.axis_speed))
            if self.invert_speed:
                speed_raw = -speed_raw
            self.state.control.linear_x = speed_raw * self.max_speed

            # 조향: 오른쪽 스틱 X → 조향각(rad) → angular_z 자리로 전송
            steer_raw = self._apply_deadzone(self._joystick.get_axis(self.axis_steer))
            self.state.control.angular_z = -steer_raw * self.max_steer

            # 표시용 raw 축
            self.state.control.raw_speed = (
                self._joystick.get_axis(self.axis_raw_speed) if self._has_raw_speed else 0.0
            )
            self.state.control.raw_steer = (
                self._joystick.get_axis(self.axis_raw_steer) if self._has_raw_steer else 0.0
            )

            # E-stop 버튼
            if self._use_estop_btn:
                btn = bool(self._joystick.get_button(self.btn_estop))
                if btn and not self._prev_btn_estop:
                    self._toggle_estop()
                self._prev_btn_estop = btn

            # UI broadcast (20Hz)
            now = time.monotonic()
            if self._loop and now - self._last_broadcast >= 0.05:
                self._loop.call_soon_threadsafe(self.state._broadcast_sync)
                self._last_broadcast = now

            time.sleep(0.02)  # 50 Hz

        pygame.quit()

    def _try_connect(self):
        pygame.joystick.quit()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            self.state.control.joystick_connected = False
            return

        joy = pygame.joystick.Joystick(0)
        joy.init()
        self._joystick = joy
        logger.info(f'Joystick connected: {joy.get_name()}')

        self._validate_config(joy)
        self.state.control.joystick_connected = True

    def _validate_config(self, joy):
        """접속 직후 한 번만 실행. 잘못된 axis/button 인덱스를 조기에 잡는다."""
        num_axes    = joy.get_numaxes()
        num_buttons = joy.get_numbuttons()

        if self.axis_speed >= num_axes:
            logger.error(
                f'axis_speed={self.axis_speed} out of range '
                f'(joystick has {num_axes} axes) — clamped to 0'
            )
            self.axis_speed = 0

        if self.axis_steer >= num_axes:
            logger.error(
                f'axis_steer={self.axis_steer} out of range '
                f'(joystick has {num_axes} axes) — clamped to 0'
            )
            self.axis_steer = 0

        # 표시용 축은 없어도 동작 — 경고만
        self._has_raw_speed = self.axis_raw_speed < num_axes
        self._has_raw_steer = self.axis_raw_steer < num_axes
        if not self._has_raw_speed:
            logger.warning(f'axis_raw_speed={self.axis_raw_speed} out of range — raw_speed disabled')
        if not self._has_raw_steer:
            logger.warning(f'axis_raw_steer={self.axis_raw_steer} out of range — raw_steer disabled')

        if self.btn_estop >= num_buttons:
            logger.warning(
                f'btn_estop={self.btn_estop} out of range '
                f'(joystick has {num_buttons} buttons) — e-stop button disabled'
            )
            self._use_estop_btn = False
        else:
            self._use_estop_btn = True

    def _on_disconnect(self):
        self._joystick = None
        self.state.control.joystick_connected = False
        self.state.control.linear_x  = 0.0
        self.state.control.angular_z = 0.0
        self.state.control.raw_speed = 0.0
        self.state.control.raw_steer = 0.0

    def _apply_deadzone(self, value: float) -> float:
        if abs(value) < self.deadzone:
            return 0.0
        sign = 1 if value > 0 else -1
        return sign * (abs(value) - self.deadzone) / (1.0 - self.deadzone)

    def _toggle_estop(self):
        if self._proto is None:
            return
        new_val = not self.state.control.estop
        self.state.control.estop = new_val
        self._proto.send_estop(new_val)
        logger.info(f'Joystick e-stop → {new_val}')
