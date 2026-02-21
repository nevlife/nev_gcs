#!/usr/bin/env python3
import argparse
import asyncio
import logging
from pathlib import Path

import yaml
import uvicorn

from state import SharedState
from vehicle_bridge import VehicleProtocol, run_send_loop
from joystick import JoystickHandler
from web.server import create_app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('main')


def load_config(path: str, overrides: dict) -> dict:
    cfg = {}
    p = Path(path)
    if p.exists():
        cfg = yaml.safe_load(p.read_text()) or {}
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


async def run(cfg: dict):
    vehicle_ip   = cfg.get('vehicle_ip',   '127.0.0.1')
    vehicle_port = cfg.get('vehicle_port', 5000)
    rx_port      = cfg.get('rx_port',      5001)
    web_port     = cfg.get('web_port',     8080)

    state = SharedState()

    loop = asyncio.get_running_loop()
    proto = VehicleProtocol(state, (vehicle_ip, vehicle_port))

    transport, _ = await loop.create_datagram_endpoint(
        lambda: proto,
        local_addr=('0.0.0.0', rx_port),
    )
    logger.info(f'UDP  listen={rx_port}  vehicle={vehicle_ip}:{vehicle_port}')

    joystick = JoystickHandler(state, cfg.get('joystick', {}))
    joystick.set_proto(proto)
    joystick.set_loop(loop)
    joystick.start()

    app = create_app(state, proto)
    uv_cfg = uvicorn.Config(
        app,
        host='0.0.0.0',
        port=web_port,
        log_level='warning',
        loop='none',
    )
    server = uvicorn.Server(uv_cfg)
    logger.info(f'Web  http://0.0.0.0:{web_port}')

    try:
        await asyncio.gather(
            run_send_loop(state, proto, cfg),
            server.serve(),
        )
    finally:
        joystick.stop()
        transport.close()
        logger.info('Shutdown complete')


def main():
    parser = argparse.ArgumentParser(description='NEV GCS')
    parser.add_argument('--config',      default='config.yaml')
    parser.add_argument('--vehicle-ip',  default=None)
    parser.add_argument('--vehicle-port',type=int, default=None)
    parser.add_argument('--rx-port', type=int, default=None)
    parser.add_argument('--web-port',    type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config, {
        'vehicle_ip':   args.vehicle_ip,
        'vehicle_port': args.vehicle_port,
        'rx_port':      args.rx_port,
        'web_port':     args.web_port,
    })

    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        logger.info('Stopped by user')


if __name__ == '__main__':
    main()
