"""
스테이션 측 경량 상태 컨테이너.
서버의 SharedState와 달리 조이스틱 제어값만 관리.
"""


class StationState:
    def __init__(self):
        self.linear_x:          float = 0.0
        self.angular_z:         float = 0.0
        self.raw_speed:         float = 0.0
        self.raw_steer:         float = 0.0
        self.estop:             bool  = False
        self.joystick_connected: bool = False
