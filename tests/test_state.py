from nev_teleop_client.state import StationState


def test_initial_values():
    s = StationState()
    assert s.linear_x == 0.0
    assert s.steer_angle == 0.0
    assert s.estop is False
    assert s.controller_connected is False


def test_set_values():
    s = StationState()
    s.linear_x = 1.0
    s.steer_angle = 0.5
    s.estop = True
    s.controller_connected = True

    assert s.linear_x == 1.0
    assert s.steer_angle == 0.5
    assert s.estop is True
    assert s.controller_connected is True
