import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from nev_teleop_client.state import StationState
from nev_teleop_client.controller.base import Controller


class DummyController(Controller):
    """테스트용 최소 구현체"""
    def name(self) -> str:
        return 'dummy'

    def poll(self) -> bool:
        return True


def test_on_disconnect_resets_state():
    state = StationState()
    state.linear_x = 1.0
    state.steer_angle = 0.5
    state.controller_connected = True

    ctrl = DummyController(state)
    ctrl.on_disconnect()

    assert state.linear_x == 0.0
    assert state.steer_angle == 0.0
    assert state.controller_connected is False


def test_stop_terminates_start():
    """start()가 별도 스레드에서 stop() 호출 시 종료되는지"""
    state = StationState()
    ctrl = DummyController(state)

    t = threading.Thread(target=ctrl.start, daemon=True)
    t.start()

    time.sleep(0.05)
    ctrl.stop()
    t.join(timeout=1.0)

    assert not t.is_alive()


def test_start_sets_controller_connected():
    state = StationState()
    ctrl = DummyController(state)

    t = threading.Thread(target=ctrl.start, daemon=True)
    t.start()
    time.sleep(0.05)
    assert state.controller_connected is True

    ctrl.stop()
    t.join(timeout=1.0)


def test_broadcast_status_rate():
    """_broadcast_status가 0.05초 간격으로 전송하는지"""
    state = StationState()
    ctrl = DummyController(state)

    mock_client = MagicMock()
    mock_loop = MagicMock()
    ctrl.setup(mock_client, mock_loop)

    # 강제로 여러 번 호출
    for _ in range(10):
        ctrl._broadcast_status()
        time.sleep(0.01)  # 10ms × 10 = 100ms 총

    # 0.05초 간격이므로 약 2회 호출 (처음 + 50ms 후)
    count = mock_loop.call_soon_threadsafe.call_count
    assert 1 <= count <= 3


def test_setup_assigns_client_and_loop():
    state = StationState()
    ctrl = DummyController(state)

    mock_client = MagicMock()
    mock_loop = MagicMock()
    ctrl.setup(mock_client, mock_loop)

    assert ctrl._client is mock_client
    assert ctrl._loop is mock_loop
