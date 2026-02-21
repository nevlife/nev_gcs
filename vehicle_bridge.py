import asyncio
import struct
import time
import logging

from state import SharedState

logger = logging.getLogger(__name__)


_RECV_FORMATS = {
    b'MS': ('<2sbbbbbbBH',
            ['header', 'requested_mode', 'active_source', 'remote_enabled',
             'nav_active', 'teleop_active', 'final_active', 'pad', 'seq']),
    b'TV': ('<2sffffffH',
            ['header', 'nav_lx', 'nav_az', 'teleop_lx', 'teleop_az',
             'final_lx', 'final_az', 'seq']),
    b'NS': ('<2sBbffH',
            ['header', 'connected', 'status_code', 'rtt_ms', 'bandwidth_mbps', 'seq']),
    b'HS': ('<2sddBBHdH',
            ['header', 'linear_vel', 'steering_angle', 'vehicle_state',
             'control_mode', 'error_code', 'battery_voltage', 'seq']),
    b'EP': ('<2sBbbH',
            ['header', 'is_estop', 'bridge_flag', 'mux_flag', 'seq']),
    b'RE': ('<2sBH',
            ['header', 'remote_enabled', 'seq']),
    b'CR': ('<2sffffffqH',
            ['header', 'cpu_usage', 'freq_mhz', 'cpu_temp', 'cpu_load',
             'load_5m', 'load_15m', 'ctx_sw', 'seq']),
    b'MR': ('<2sqqqqfH',
            ['header', 'total_bytes', 'avail_bytes', 'used_bytes',
             'free_bytes', 'mem_pct', 'seq']),
    b'GR': ('<2sifffffH',
            ['header', 'gpu_idx', 'gpu_usage', 'gpu_mem_used',
             'gpu_mem_total', 'gpu_temp', 'gpu_power', 'seq']),
    b'DI': ('<2sqqqqqqqH',
            ['header', 'io_rd_cnt', 'io_wr_cnt', 'io_rd_bytes',
             'io_wr_bytes', 'io_rd_ms', 'io_wr_ms', 'io_busy_ms', 'seq']),
    b'DP': ('<2sB32sqqqfBH',
            ['header', 'idx', 'mountpoint', 'total_bytes',
             'used_bytes', 'free_bytes', 'percent', 'accessible', 'seq']),
    b'NM': ('<2siiiH',
            ['header', 'net_total_ifaces', 'net_active_ifaces', 'net_down_ifaces', 'seq']),
    b'NF': ('<2sB16sBiiddqqqqqqqqH',
            ['header', 'idx', 'name', 'is_up', 'mtu', 'speed_mbps',
             'in_bps', 'out_bps', 'rx_bytes', 'tx_bytes',
             'rx_packets', 'tx_packets', 'rx_errors', 'tx_errors',
             'rx_dropped', 'tx_dropped', 'seq']),
}

_HEADER_TO_KEY = {
    b'MS': 'mux',
    b'TV': 'twist',
    b'NS': 'network',
    b'HS': 'hunter',
    b'EP': 'estop',
    b'RE': None,
    b'CR': 'resources',
    b'MR': None,   # bytes → MB conversion needed
    b'GR': None,
    b'DI': None,
    b'DP': None,   # bytes field needs decode
    b'NM': 'resources',
    b'NF': None,   # bytes field needs decode
}

# Fields that should be cast to bool
_BOOL_FIELDS = {
    'is_estop', 'connected', 'nav_active', 'teleop_active',
    'final_active', 'remote_enabled', 'final_active',
}


class VehicleProtocol(asyncio.DatagramProtocol):
    def __init__(self, state: SharedState, vehicle_addr: tuple):
        self.state = state
        self.vehicle_addr = vehicle_addr
        self.transport: asyncio.DatagramTransport | None = None
        self._seq = 0

    def connection_made(self, transport):
        self.transport = transport
        logger.info(f'UDP socket ready → vehicle {self.vehicle_addr}')

    def datagram_received(self, data: bytes, addr):
        if len(data) < 2:
            return

        header = data[:2]
        fmt_info = _RECV_FORMATS.get(header)
        if fmt_info is None:
            return

        fmt, fields = fmt_info
        if len(data) < struct.calcsize(fmt):
            return

        try:
            values = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        except struct.error:
            return

        pkt = {k: v for k, v in zip(fields, values)
               if k not in ('header', 'pad', 'seq')}

        for k in _BOOL_FIELDS:
            if k in pkt:
                pkt[k] = bool(pkt[k])

        key = _HEADER_TO_KEY.get(header)
        if header == b'RE':
            self.state.update_remote_enabled(bool(pkt['remote_enabled']))
        elif header == b'MR':
            self.state.update_packet('resources', {
                'ram_total': pkt['total_bytes'] // (1024 * 1024),
                'ram_used':  pkt['used_bytes']  // (1024 * 1024),
            })
        elif header == b'GR':
            self.state.update_gpu(int(pkt['gpu_idx']), {
                'gpu_usage':     pkt['gpu_usage'],
                'gpu_mem_used':  pkt['gpu_mem_used'],
                'gpu_mem_total': pkt['gpu_mem_total'],
                'gpu_temp':      pkt['gpu_temp'],
                'gpu_power':     pkt['gpu_power'],
            })
        elif header == b'DI':
            self.state.last_vehicle_recv = time.monotonic()
        elif header == b'DP':
            mp = pkt['mountpoint'].rstrip(b'\x00').decode('utf-8', errors='replace')
            self.state.update_disk_partition(int(pkt['idx']), {
                'mountpoint': mp,
                'total_bytes': pkt['total_bytes'],
                'used_bytes':  pkt['used_bytes'],
                'percent':     pkt['percent'],
                'accessible':  bool(pkt['accessible']),
            })
        elif header == b'NF':
            name = pkt['name'].rstrip(b'\x00').decode('utf-8', errors='replace')
            self.state.update_net_interface(int(pkt['idx']), {
                'name':       name,
                'is_up':      bool(pkt['is_up']),
                'speed_mbps': pkt['speed_mbps'],
                'in_bps':     pkt['in_bps'],
                'out_bps':    pkt['out_bps'],
            })
        elif key:
            self.state.update_packet(key, pkt)

    def error_received(self, exc):
        logger.warning(f'UDP error: {exc}')

    def _next_seq(self) -> int:
        s = self._seq
        self._seq = (self._seq + 1) % 65536
        return s

    def send_heartbeat(self):
        if not self.transport:
            return
        pkt = struct.pack('<2sdH', b'HB', time.time(), self._next_seq())
        self.transport.sendto(pkt, self.vehicle_addr)

    def send_teleop(self, linear_x: float, angular_z: float):
        if not self.transport:
            return
        pkt = struct.pack('<2sffH', b'TC',
                          round(linear_x, 2), round(angular_z, 2),
                          self._next_seq())
        self.transport.sendto(pkt, self.vehicle_addr)

    def send_estop(self, activate: bool):
        if not self.transport:
            return
        pkt = struct.pack('<2sBH', b'ES', 1 if activate else 0, self._next_seq())
        self.transport.sendto(pkt, self.vehicle_addr)

    def send_cmd_mode(self, mode: int):
        if not self.transport:
            return
        pkt = struct.pack('<2sbH', b'CM', mode, self._next_seq())
        self.transport.sendto(pkt, self.vehicle_addr)


async def run_send_loop(state: SharedState, proto: VehicleProtocol, cfg: dict):
    """Periodic heartbeat and teleop sender."""
    hb_interval   = 1.0 / cfg.get('heartbeat_rate', 5.0)
    tc_interval   = 1.0 / cfg.get('teleop_rate', 20.0)
    push_interval = cfg.get('state_push_interval', 0.5)

    last_hb   = 0.0
    last_tc   = 0.0
    last_push = 0.0

    while True:
        now = time.monotonic()

        if now - last_hb >= hb_interval:
            proto.send_heartbeat()
            last_hb = now

        if now - last_tc >= tc_interval:
            ctrl = state.control
            if ctrl.mode == 2 and not ctrl.estop:
                proto.send_teleop(ctrl.linear_x, ctrl.angular_z)
            last_tc = now

        # Periodic UI push (so joystick values and alerts stay fresh)
        if now - last_push >= push_interval:
            state._validate()
            state._broadcast_sync()
            last_push = now

        await asyncio.sleep(0.01)
