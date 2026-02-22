import asyncio
import json
import logging
import time

import zenoh

from state import SharedState

logger = logging.getLogger(__name__)


class VehicleProtocol:
    """
    Zenoh-based vehicle bridge.
    Subscribes to nev/vehicle/* topics and publishes nev/gcs/* topics.
    All zenoh callbacks run in a zenoh background thread and are safely
    forwarded to the asyncio event loop via call_soon_threadsafe().
    """

    def __init__(self, state: SharedState, loop: asyncio.AbstractEventLoop):
        self.state = state
        self._loop = loop
        self._session: zenoh.Session | None = None
        self._pubs: dict = {}
        self._subs: list = []
        self._seq  = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, locator: str = '') -> None:
        conf = zenoh.Config()
        if locator:
            conf.insert_json5('connect/endpoints', json.dumps([locator]))
        self._session = zenoh.open(conf)

        # Publishers (GCS → vehicle)
        for key in ('nev/gcs/heartbeat', 'nev/gcs/teleop',
                    'nev/gcs/estop', 'nev/gcs/cmd_mode'):
            self._pubs[key] = self._session.declare_publisher(key)

        # Subscribers (vehicle → GCS)
        self._subs = [
            self._session.declare_subscriber('nev/vehicle/mux',     self._on_mux),
            self._session.declare_subscriber('nev/vehicle/twist',   self._on_twist),
            self._session.declare_subscriber('nev/vehicle/network', self._on_network),
            self._session.declare_subscriber('nev/vehicle/hunter',  self._on_hunter),
            self._session.declare_subscriber('nev/vehicle/estop',   self._on_estop),
            self._session.declare_subscriber('nev/vehicle/cpu',     self._on_cpu),
            self._session.declare_subscriber('nev/vehicle/mem',     self._on_mem),
            self._session.declare_subscriber('nev/vehicle/gpu',     self._on_gpu),
            self._session.declare_subscriber('nev/vehicle/disk',    self._on_disk),
            self._session.declare_subscriber('nev/vehicle/net',     self._on_net),
        ]
        logger.info(f'Zenoh bridge started → {locator or "auto-discovery"}')

    def stop(self) -> None:
        for sub in self._subs:
            sub.undeclare()
        for pub in self._pubs.values():
            pub.undeclare()
        if self._session:
            self._session.close()

    # ── Thread-safe asyncio bridge ────────────────────────────────────────────

    def _call(self, fn, *args):
        """Schedule a state-update call on the asyncio loop thread."""
        self._loop.call_soon_threadsafe(fn, *args)

    def _call_fn(self, fn):
        """Schedule an arbitrary callable (no args) on the asyncio loop."""
        self._loop.call_soon_threadsafe(fn)

    # ── Vehicle → GCS subscribers ─────────────────────────────────────────────

    def _on_mux(self, sample):
        data = json.loads(bytes(sample.payload))
        def _update():
            self.state.update_packet('mux', data)
            self.state.update_remote_enabled(data.get('remote_enabled', False))
        self._call_fn(_update)

    def _on_twist(self, sample):
        data = json.loads(bytes(sample.payload))
        self._call(self.state.update_packet, 'twist', data)

    def _on_network(self, sample):
        data = json.loads(bytes(sample.payload))
        self._call(self.state.update_packet, 'network', data)

    def _on_hunter(self, sample):
        data = json.loads(bytes(sample.payload))
        self._call(self.state.update_packet, 'hunter', data)

    def _on_estop(self, sample):
        data = json.loads(bytes(sample.payload))
        self._call(self.state.update_packet, 'estop', data)

    def _on_cpu(self, sample):
        data = json.loads(bytes(sample.payload))
        self._call(self.state.update_packet, 'resources', data)

    def _on_mem(self, sample):
        data = json.loads(bytes(sample.payload))
        self._call(self.state.update_packet, 'resources', data)

    def _on_gpu(self, sample):
        gpus = json.loads(bytes(sample.payload))
        def _update():
            for g in gpus:
                self.state.update_gpu(g['idx'], {
                    'gpu_usage':    g['gpu_usage'],
                    'gpu_mem_used': g['gpu_mem_used'],
                    'gpu_mem_total':g['gpu_mem_total'],
                    'gpu_temp':     g['gpu_temp'],
                    'gpu_power':    g['gpu_power'],
                })
        self._call_fn(_update)

    def _on_disk(self, sample):
        data = json.loads(bytes(sample.payload))
        def _update():
            self.state.last_vehicle_recv = time.monotonic()
            for p in data.get('partitions', []):
                self.state.update_disk_partition(p['idx'], {
                    'mountpoint':  p['mountpoint'],
                    'total_bytes': p['total_bytes'],
                    'used_bytes':  p['used_bytes'],
                    'percent':     p['percent'],
                    'accessible':  p['accessible'],
                })
        self._call_fn(_update)

    def _on_net(self, sample):
        data = json.loads(bytes(sample.payload))
        def _update():
            self.state.update_packet('resources', {
                'net_total_ifaces':  data['net_total_ifaces'],
                'net_active_ifaces': data['net_active_ifaces'],
                'net_down_ifaces':   data['net_down_ifaces'],
            })
            for iface in data.get('interfaces', []):
                self.state.update_net_interface(iface['idx'], {
                    'name':       iface['name'],
                    'is_up':      iface['is_up'],
                    'speed_mbps': iface['speed_mbps'],
                    'in_bps':     iface['in_bps'],
                    'out_bps':    iface['out_bps'],
                })
        self._call_fn(_update)

    # ── GCS → vehicle publishers ──────────────────────────────────────────────

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
        self._zput('nev/gcs/heartbeat', {'ts': time.time(), 'seq': self._next_seq()})

    def send_teleop(self, linear_x: float, angular_z: float):
        self._zput('nev/gcs/teleop', {
            'linear_x': round(linear_x, 3),
            'angular_z': round(angular_z, 3),
            'seq': self._next_seq(),
        })

    def send_estop(self, activate: bool):
        self._zput('nev/gcs/estop', {'active': activate, 'seq': self._next_seq()})

    def send_cmd_mode(self, mode: int):
        self._zput('nev/gcs/cmd_mode', {'mode': mode, 'seq': self._next_seq()})


# ── Send loop (asyncio) ───────────────────────────────────────────────────────

async def run_send_loop(state: SharedState, proto: VehicleProtocol, cfg: dict):
    """Periodic heartbeat and teleop sender."""
    hb_interval   = 1.0 / cfg.get('heartbeat_rate',   5.0)
    tc_interval   = 1.0 / cfg.get('teleop_rate',      20.0)
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

        if now - last_push >= push_interval:
            state._validate()
            state._broadcast_sync()
            last_push = now

        await asyncio.sleep(0.01)
