#!/usr/bin/env python3
import argparse
import asyncio
import logging
import threading

from nev_teleop_client.config import load_config
from nev_teleop_client.state import StationState
from nev_teleop_client.client import StationClient
from nev_teleop_client.controller import create_controller
from nev_teleop_client.send_loop import run_send_loop

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('main')


def main():
    parser = argparse.ArgumentParser(description='NEV Teleop Client')
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--server-locator', default=None)
    args = parser.parse_args()

    cfg = load_config(args.config, {'server_zenoh_locator': args.server_locator})
    locator = cfg.get('server_zenoh_locator', '')

    state  = StationState()
    client = StationClient()
    client.start(locator)

    loop = asyncio.new_event_loop()
    async_stop_event = asyncio.Event()
    done_event = threading.Event()
    controller = create_controller(state, cfg)
    controller.setup(client, loop)

    async def async_run():
        logger.info(f'Station started → server: {locator or "auto-discovery"}')
        try:
            await run_send_loop(client, state, cfg, stop_event=async_stop_event)
        finally:
            client.stop()
            done_event.set()
            logger.info('Shutdown complete')

    t = threading.Thread(target=loop.run_until_complete, args=(async_run(),), daemon=True)
    t.start()

    try:
        controller.start()
    except KeyboardInterrupt:
        logger.info('Stopped by user')
    finally:
        controller.stop()
        loop.call_soon_threadsafe(async_stop_event.set)
        done_event.wait(timeout=3.0)
        t.join(timeout=1.0)


if __name__ == '__main__':
    main()
