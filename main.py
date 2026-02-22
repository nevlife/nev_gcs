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
    web_port = cfg.get('web_port', 8080)
    locator  = cfg.get('zenoh_locator', '')

    state = SharedState()
    loop  = asyncio.get_running_loop()

    proto = VehicleProtocol(state, loop)
    proto.start(locator)
    logger.info(f'Zenoh bridge started → {locator or "auto-discovery"}')

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
        proto.stop()
        logger.info('Shutdown complete')


def main():
    parser = argparse.ArgumentParser(description='NEV GCS')
    parser.add_argument('--config',       default='config.yaml')
    parser.add_argument('--zenoh-locator',default=None)
    parser.add_argument('--web-port',     type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config, {
        'zenoh_locator': args.zenoh_locator,
        'web_port':      args.web_port,
    })

    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        logger.info('Stopped by user')


if __name__ == '__main__':
    main()
