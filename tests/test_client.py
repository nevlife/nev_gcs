import json
from unittest.mock import MagicMock, patch, call

import pytest

# zenoh를 mock으로 대체 후 import
import sys
mock_zenoh = MagicMock()
mock_zenoh.Reliability.BEST_EFFORT  = 'best_effort'
mock_zenoh.Reliability.RELIABLE     = 'reliable'
mock_zenoh.CongestionControl.DROP   = 'drop'
mock_zenoh.CongestionControl.BLOCK  = 'block'
mock_zenoh.Priority.DATA_LOW        = 'data_low'
mock_zenoh.Priority.INTERACTIVE_HIGH = 'interactive_high'
mock_zenoh.Priority.REAL_TIME       = 'real_time'
mock_zenoh.Priority.BACKGROUND      = 'background'
sys.modules['zenoh'] = mock_zenoh

from nev_teleop_client.client import StationClient


@pytest.fixture
def client():
    mock_session = MagicMock()
    mock_pub = MagicMock()
    mock_session.declare_publisher.return_value = mock_pub
    mock_zenoh.open.return_value = mock_session
    mock_zenoh.Config.return_value = MagicMock()

    c = StationClient()
    c.start('')
    return c, mock_pub


def test_send_teleop_payload(client):
    c, pub = client
    c.send_teleop(1.23456, 0.12345)

    pub.put.assert_called_once()
    data = json.loads(pub.put.call_args[0][0])
    assert data == {'linear_x': 1.235, 'steer_angle': 0.1235}


def test_send_teleop_rounding(client):
    c, pub = client
    c.send_teleop(0.0, 0.0)
    data = json.loads(pub.put.call_args[0][0])
    assert data['linear_x'] == 0.0
    assert data['steer_angle'] == 0.0


def test_send_estop_active(client):
    c, pub = client
    c.send_estop(True)
    data = json.loads(pub.put.call_args[0][0])
    assert data == {'active': True}


def test_send_estop_inactive(client):
    c, pub = client
    c.send_estop(False)
    data = json.loads(pub.put.call_args[0][0])
    assert data == {'active': False}


def test_send_client_heartbeat_has_ts(client):
    c, pub = client
    c.send_client_heartbeat()
    data = json.loads(pub.put.call_args[0][0])
    assert 'ts' in data
    assert isinstance(data['ts'], float)


def test_send_cmd_mode(client):
    c, pub = client
    c.send_cmd_mode(2)
    data = json.loads(pub.put.call_args[0][0])
    assert data == {'mode': 2}


def test_send_controller_heartbeat(client):
    c, pub = client
    c.send_controller_heartbeat(True)
    data = json.loads(pub.put.call_args[0][0])
    assert data == {'connected': True}


def test_publish_exception_does_not_raise(client):
    c, pub = client
    pub.put.side_effect = Exception('zenoh error')
    c.send_teleop(1.0, 0.0)  # 예외가 밖으로 새면 안 됨
