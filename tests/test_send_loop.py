import asyncio
from unittest.mock import MagicMock, patch

import pytest

from nev_teleop_client.send_loop import run_send_loop
from nev_teleop_client.state import StationState


def make_client():
    c = MagicMock()
    c.send_client_heartbeat = MagicMock()
    c.send_teleop = MagicMock()
    return c


async def run_for(coro, seconds: float):
    """코루틴을 일정 시간 후 강제 종료"""
    try:
        await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        pass


def test_teleop_sent_with_state_values():
    """send_teleop에 state 값이 올바르게 전달되는지"""
    state = StationState()
    state.linear_x = 0.5
    state.steer_angle = 0.3
    client = make_client()

    cfg = {'teleop_rate': 100.0, 'heartbeat_rate': 1.0}  # 빠르게 트리거

    asyncio.run(run_for(run_send_loop(client, state, cfg), 0.05))

    assert client.send_teleop.called
    args = client.send_teleop.call_args[0]
    assert args[0] == 0.5
    assert args[1] == 0.3


def test_heartbeat_sent():
    """heartbeat이 전송되는지"""
    state = StationState()
    client = make_client()
    cfg = {'teleop_rate': 1.0, 'heartbeat_rate': 100.0}

    asyncio.run(run_for(run_send_loop(client, state, cfg), 0.05))

    assert client.send_client_heartbeat.called


def test_teleop_rate_respected():
    """teleop_rate 설정에 따라 전송 횟수가 조절되는지"""
    state = StationState()
    client = make_client()

    # 10Hz로 0.15초 → 약 1~2회
    cfg = {'teleop_rate': 10.0, 'heartbeat_rate': 1.0}
    asyncio.run(run_for(run_send_loop(client, state, cfg), 0.15))

    count = client.send_teleop.call_count
    assert 1 <= count <= 3


def test_default_rates_used_when_cfg_empty():
    """cfg가 비어있어도 기본값(20Hz teleop, 5Hz hb)으로 동작"""
    state = StationState()
    client = make_client()

    asyncio.run(run_for(run_send_loop(client, state, {}), 0.1))

    # 20Hz로 0.1초 → 최소 1회는 전송돼야 함
    assert client.send_teleop.call_count >= 1
