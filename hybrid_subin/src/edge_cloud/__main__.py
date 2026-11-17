"""Model-free synthetic event smoke test; never use to fabricate real observations."""
import argparse
from collections import deque
import json
import logging
import time
from types import SimpleNamespace
from .config import Config
from .runtime import EdgeRuntime
from .slots import Occupancy


def main():
    parser = argparse.ArgumentParser(description='SPASIBA synthetic MQTT/outbox test (no OCR models)')
    parser.add_argument('--config', required=True)
    parser.add_argument('--plate', default='12가3456')
    parser.add_argument('--wait', type=float, default=10)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--synthetic', action='store_true', help='Required: acknowledges synthetic test data')
    args = parser.parse_args()
    if not args.synthetic:
        parser.error('pass --synthetic; use a dedicated test slot/broker/database')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config = Config.load(args.config)
    if not config.single_slot:
        parser.error('synthetic test requires an explicitly configured single_slot')
    runtime = EdgeRuntime(config, network=not args.offline)
    try:
        runtime.store.set_occupancy(config.single_slot, Occupancy.OCCUPIED)
        track = SimpleNamespace(readings=deque([(args.plate, 0.9)] * config.min_votes, maxlen=10))
        events = runtime.observe([({'bbox':[0,0,100,30]}, track)])
        print(json.dumps(events, ensure_ascii=False, indent=2))
        until = time.monotonic() + args.wait
        while runtime.store.count() and time.monotonic() < until and not args.offline:
            time.sleep(0.1)
        print(f'pending={runtime.store.count()}')
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
