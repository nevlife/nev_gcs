import math
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from nev_teleop_client.state import StationState


# ── pygame mock ──────────────────────────────────────────────────────────────
def make_pygame_mock(num_axes=6, num_buttons=8):
    pg = MagicMock()
    pg.JOYDEVICEADDED   = 1536
    pg.JOYDEVICEREMOVED = 1537
    pg.JOYBUTTONDOWN    = 1539

    joy = MagicMock()
    joy.get_numaxes.return_value    = num_axes
    joy.get_numbuttons.return_value = num_buttons
    joy.get_instance_id.return_value = 0
    joy.get_name.return_value = 'Mock Joystick'
    joy.get_axis.return_value = 0.0

    pg.joystick.Joystick.return_value = joy
    pg.event.get.return_value = []
    return pg, joy


@pytest.fixture
def mocked_pygame():
    pg, joy = make_pygame_mock()
    with patch.dict(sys.modules, {'pygame': pg}):
        # 모듈 재로드 없이 패치가 적용되도록 joystick 모듈의 _HAS_PYGAME도 패치
        import nev_teleop_client.controller.joystick as jmod
        original = jmod._HAS_PYGAME
        jmod._HAS_PYGAME = True
        yield pg, joy, jmod
        jmod._HAS_PYGAME = original


# ── deadzone 테스트 (pygame 불필요) ─────────────────────────────────────────
from nev_teleop_client.controller.joystick import JoystickController


def make_ctrl(cfg=None):
    return JoystickController(StationState(), cfg or {})


def test_deadzone_zero_within_zone():
    ctrl = make_ctrl({'deadzone': 0.1})
    assert ctrl._apply_deadzone(0.05) == 0.0
    assert ctrl._apply_deadzone(-0.05) == 0.0


def test_deadzone_zero_at_boundary():
    ctrl = make_ctrl({'deadzone': 0.1})
    assert ctrl._apply_deadzone(0.1) == 0.0


def test_deadzone_nonzero_outside():
    ctrl = make_ctrl({'deadzone': 0.1})
    val = ctrl._apply_deadzone(1.0)
    assert val > 0.0


def test_deadzone_full_deflection():
    ctrl = make_ctrl({'deadzone': 0.1})
    assert ctrl._apply_deadzone(1.0) == pytest.approx(1.0)
    assert ctrl._apply_deadzone(-1.0) == pytest.approx(-1.0)


def test_deadzone_sign_preserved():
    ctrl = make_ctrl({'deadzone': 0.1})
    assert ctrl._apply_deadzone(0.5) > 0
    assert ctrl._apply_deadzone(-0.5) < 0


# ── config 기본값 ─────────────────────────────────────────────────────────────
def test_default_config():
    ctrl = make_ctrl()
    assert ctrl.axis_speed == 1
    assert ctrl.axis_steer == 3
    assert ctrl.btn_estop  == 4
    assert ctrl.max_speed  == 1.0
    assert ctrl.max_steer  == pytest.approx(math.radians(27.0))
    assert ctrl.deadzone   == 0.05
    assert ctrl.invert_speed is True


def test_custom_config():
    cfg = {
        'axis_speed': 0,
        'axis_steer': 2,
        'max_speed': 2.0,
        'max_steer_deg': 45.0,
        'deadzone': 0.15,
        'invert_speed': False,
    }
    ctrl = make_ctrl(cfg)
    assert ctrl.axis_speed == 0
    assert ctrl.axis_steer == 2
    assert ctrl.max_speed  == 2.0
    assert ctrl.max_steer  == pytest.approx(math.radians(45.0))
    assert ctrl.deadzone   == 0.15
    assert ctrl.invert_speed is False


# ── pygame 없을 때 start() 동작 ──────────────────────────────────────────────
def test_start_without_pygame_blocks_until_stop():
    import nev_teleop_client.controller.joystick as jmod
    original = jmod._HAS_PYGAME
    jmod._HAS_PYGAME = False

    try:
        state = StationState()
        ctrl = JoystickController(state, {})

        started = threading.Event()
        original_sleep = time.sleep

        def patched_sleep(s):
            started.set()
            original_sleep(s)

        t = threading.Thread(target=lambda: ctrl.start(), daemon=True)
        with patch('nev_teleop_client.controller.joystick.time') as mock_time:
            mock_time.sleep = patched_sleep
            t.start()
            started.wait(timeout=1.0)
            assert t.is_alive(), 'pygame 없어도 start()가 블로킹이어야 함'
            ctrl.stop()
            t.join(timeout=1.0)
            assert not t.is_alive()
    finally:
        jmod._HAS_PYGAME = original


# ── _connect 축 범위 초과 시 클램핑 ──────────────────────────────────────────
def test_connect_clamps_out_of_range_axes():
    import nev_teleop_client.controller.joystick as jmod

    pg, joy = make_pygame_mock(num_axes=2, num_buttons=8)
    jmod._HAS_PYGAME = True

    with patch.dict(sys.modules, {'pygame': pg}):
        ctrl = JoystickController(StationState(), {'axis_speed': 5, 'axis_steer': 5})
        ctrl._joystick = None
        with patch('nev_teleop_client.controller.joystick.pygame', pg):
            ctrl._connect(0)

    assert ctrl.axis_speed == 0
    assert ctrl.axis_steer == 0
