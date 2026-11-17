import logging
from .config import Config
from .crops import CropCache
from .events import consensus, make_event, normalize_plate
from .slots import Occupancy, SlotResolver
from .store import Store
from .transport import MQTTTransport

LOG = logging.getLogger(__name__)


class EdgeRuntime:
    def __init__(self, config, network=True):
        self.config = config
        self.store = Store(config.database, config.max_pending)
        self.resolver = SlotResolver(config)
        self.crops = CropCache(config.crop_ttl) if config.crop_enabled else None
        self.transport = None
        if network:
            try:
                self.transport = MQTTTransport(config, self.store, self.crops)
                self.transport.start()
            except Exception:
                LOG.exception('MQTT unavailable; OCR continues with durable local outbox')

    def observe(self, pairs):
        candidates = {}
        for result, track in pairs:
            reading = consensus(track.readings, self.config.min_votes)
            slot = self.resolver.resolve(result.get('bbox'))
            if slot:
                candidates.setdefault(slot, []).append((reading, result))
        emitted = []
        for slot, values in candidates.items():
            # Multiple visible tracks in a slot are ambiguous, even if text agrees.
            if len(values) != 1:
                continue
            state = self.store.occupancy(slot)
            if state == Occupancy.EMPTY or (state == Occupancy.UNKNOWN and not self.config.publish_on_consensus):
                continue
            reading, result = values[0]
            if not reading or result.get('format_valid') is False:
                continue
            if result.get('plate_text') and normalize_plate(result['plate_text']) != reading[0]:
                continue  # Do not publish stale consensus over a contradictory current read.
            event = make_event(self.config, slot, reading)
            if self.store.enqueue(event):
                emitted.append(event)
                LOG.info('event queued event_id=%s slot=%s votes=%s frames=%s',
                         event['event_id'], slot, event['votes'], event['frames'])
                if self.crops and result.get('crop') is not None:
                    try:
                        self.crops.put(event, result['crop'])
                    except Exception:
                        LOG.exception('optional crop encoding failed')
        return emitted

    def close(self):
        if self.transport:
            self.transport.stop()
        self.store.close()


def add_arguments(parser):
    parser.add_argument('--mqtt', action='store_true', help='Enable optional Edge–Cloud integration')
    parser.add_argument('--edge-config', help='Edge JSON configuration path')


def optional_runtime(args):
    if not args.mqtt:
        return None
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        if not args.edge_config:
            raise ValueError('--mqtt requires --edge-config')
        return EdgeRuntime(Config.load(args.edge_config))
    except Exception:
        LOG.exception('Edge config invalid; integration disabled, OCR continues')
        return None
