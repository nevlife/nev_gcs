import json
import time
import dataclasses
from dataclasses import dataclass, field
from typing import List

@dataclass
class MuxStatus:
    requested_mode: int = -1      # -1:idle 0:ctrl 1:nav 2:remote
    active_source:  int = -1      # 0:nav 1:teleop -1:none
    remote_enabled: bool = False
    nav_active:     bool = False
    teleop_active:  bool = False
    final_active:   bool = False


@dataclass
class TwistValues:
    nav_lx:    float = 0.0
    nav_az:    float = 0.0
    teleop_lx: float = 0.0
    teleop_az: float = 0.0
    final_lx:  float = 0.0
    final_az:  float = 0.0


@dataclass
class NetworkStatus:
    connected:      bool  = False
    status_code:    int   = 2     # 0:ok 1:hb_delay 2:socket_err
    rtt_ms:         float = 0.0
    bandwidth_mbps: float = 0.0


@dataclass
class HunterStatus:
    linear_vel:      float = 0.0
    steering_angle:  float = 0.0
    vehicle_state:   int   = 0 #
    control_mode:    int   = 0
    error_code:      int   = 0
    battery_voltage: float = 0.0


@dataclass
class EStopStatus:
    is_estop:    bool = False
    bridge_flag: int  = 0   # 0:ok 1:server_cmd 2:socket 3:hb_timeout 4:ctrl_timeout
    mux_flag:    int  = 0   # 0:ok 1:remote+nav+no_teleop


@dataclass
class SystemResources:
    cpu_phys:          int   = 0
    cpu_logic:         int   = 0
    cpu_usage:         float = 0.0
    cpu_temp:          float = 0.0
    cpu_load:          float = 0.0
    ram_total:         int   = 0
    ram_used:          int   = 0
    net_total_ifaces:  int   = 0
    net_active_ifaces: int   = 0
    net_down_ifaces:   int   = 0


@dataclass
class ControlState:
    mode:               int   = -1     # mode sent by server
    estop:              bool  = False  # server-side e-stop flag
    linear_x:           float = 0.0
    angular_z:          float = 0.0
    raw_speed:          float = 0.0   # 전 원시 축값
    raw_steer:          float = 0.0   # 전 원시 축값
    joystick_connected: bool  = False


@dataclass
class Alert:
    level:   str = 'ok'
    message: str = ''


class SharedState:
    def __init__(self):
        self.mux       = MuxStatus()
        self.twist     = TwistValues()
        self.network   = NetworkStatus()
        self.hunter    = HunterStatus()
        self.estop     = EStopStatus()
        self.resources = SystemResources()
        self.remote_enabled: bool = False
        self.control   = ControlState()
        self.alerts: List[Alert] = []

        self.last_vehicle_recv: float = 0.0

        self.gpu_list:        list = []   # [{'gpu_usage':, 'gpu_mem_used':, ...}, ...]
        self.disk_partitions: list = []   # [{'mountpoint':, 'total_bytes':, ...}, ...]
        self.net_interfaces:  list = []   # [{'name':, 'is_up':, 'in_bps':, ...}, ...]

        self._subscribers: list = []

    def update_packet(self, key: str, data: dict):
        """Update a sub-struct by key, then validate and broadcast."""
        obj = getattr(self, key, None)
        if obj is None:
            return
        for k, v in data.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        self.last_vehicle_recv = time.monotonic()
        self._validate()
        self._broadcast_sync()

    def _upsert_list(self, lst: list, idx: int, data: dict):
        """idx 위치 dict를 upsert. 빈 슬롯은 {}로 채운다."""
        if idx >= len(lst):
            lst.extend({} for _ in range(idx - len(lst) + 1))
        lst[idx].update(data)

    def update_gpu(self, idx: int, data: dict):
        self._upsert_list(self.gpu_list, idx, data)
        self.last_vehicle_recv = time.monotonic()
        self._broadcast_sync()

    def update_disk_partition(self, idx: int, data: dict):
        self._upsert_list(self.disk_partitions, idx, data)
        self.last_vehicle_recv = time.monotonic()
        self._broadcast_sync()

    def update_net_interface(self, idx: int, data: dict):
        self._upsert_list(self.net_interfaces, idx, data)
        self.last_vehicle_recv = time.monotonic()
        self._broadcast_sync()

    def update_remote_enabled(self, val: bool):
        self.remote_enabled = val
        self._broadcast_sync()

    def _validate(self):
        alerts: List[Alert] = []

        # E-stop active but vehicle still moving
        if self.estop.is_estop and (
            abs(self.twist.final_lx) > 0.05 or abs(self.twist.final_az) > 0.05
        ):
            alerts.append(Alert('error', 'E-STOP active but vehicle is moving!'))

        # Server sent e-stop but vehicle hasn't confirmed yet
        if self.control.estop and not self.estop.is_estop:
            alerts.append(Alert('warn', 'E-stop sent — waiting for vehicle confirmation'))

        # Remote mode active but no teleop arriving
        if (self.mux.requested_mode == 2
                and self.mux.remote_enabled
                and not self.mux.teleop_active):
            alerts.append(Alert('warn', 'Remote mode active but no teleop commands received'))

        # Vehicle hasn't sent any data for a while
        if self.last_vehicle_recv > 0:
            age = time.monotonic() - self.last_vehicle_recv
            if age > 3.0:
                alerts.append(Alert('error', f'No vehicle data for {age:.1f}s'))

        self.alerts = alerts


    def _broadcast_sync(self):
        data = self.to_json()
        for q in self._subscribers[:]:
            try:
                q.put_nowait(data)
            except Exception:
                pass

    def add_subscriber(self, q):
        self._subscribers.append(q)

    def remove_subscriber(self, q):
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass


    def to_json(self) -> str:
        def _d(obj):
            return dataclasses.asdict(obj)

        return json.dumps({
            'mux':             _d(self.mux),
            'twist':           _d(self.twist),
            'network':         _d(self.network),
            'hunter':          _d(self.hunter),
            'estop':           _d(self.estop),
            'resources':       _d(self.resources),
            'gpu_list':        self.gpu_list,
            'disk_partitions': self.disk_partitions,
            'net_interfaces':  self.net_interfaces,
            'remote_enabled':  self.remote_enabled,
            'control':         _d(self.control),
            'alerts':          [_d(a) for a in self.alerts],
            'server_time':     time.time(),
            'vehicle_age':     (time.monotonic() - self.last_vehicle_recv)
                               if self.last_vehicle_recv > 0 else -1,
        })
