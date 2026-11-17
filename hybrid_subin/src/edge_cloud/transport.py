from __future__ import annotations
import json
import logging
import queue
import ssl
import threading
from .events import now

LOG = logging.getLogger(__name__)


class MQTTTransport:
    def __init__(self, config, store, crops=None, client=None):
        import paho.mqtt.client as mqtt
        if not config.host:
            raise ValueError("SPASIBA_HOST or config host is required")
        self.config, self.store, self.crops = config, store, crops
        self.connected, self.stopping = threading.Event(), threading.Event()
        self.requests = queue.Queue(maxsize=8)
        self.acks = queue.SimpleQueue()
        self.client = client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                            client_id=f'spasiba-{config.camera_id}',
                                            clean_session=False, protocol=mqtt.MQTTv311)
        self.client.max_inflight_messages_set(4)
        self.client.max_queued_messages_set(16)
        self.client.connect_timeout = 3.0
        if config.username:
            self.client.username_pw_set(config.username, config.password)
        if config.tls:
            context = ssl.create_default_context(cafile=config.ca)
            if config.cert:
                context.load_cert_chain(config.cert, config.key)
            self.client.tls_set_context(context)
        self.status_topic = config.status_topic.format(zone_id=config.zone_id, camera_id=config.camera_id)
        self.client.will_set(self.status_topic, json.dumps({'state':'offline'}), qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._connect
        self.client.on_disconnect = self._disconnect
        self.client.on_connect_fail = lambda *args: LOG.warning('MQTT connect failed; retrying')
        self.client.on_message = self._message
        self.client.on_publish = self._publish_ack
        self.thread = threading.Thread(target=self._run, name='spasiba-outbox', daemon=True)

    def _connect(self, client, userdata, flags, reason, properties):
        if reason != 0:
            LOG.warning('MQTT connection refused code=%s', reason)
            return
        LOG.info('MQTT online ts=%s', now())
        client.publish(self.status_topic, json.dumps({'state':'online', 'ts':now()}), qos=1, retain=True)
        if self.config.crop_enabled:
            client.subscribe(self.config.topic('crop_request'), qos=1)
        self.connected.set()

    def _disconnect(self, client, userdata, flags, reason, properties):
        self.connected.clear()
        LOG.info('MQTT disconnected code=%s ts=%s', reason, now())

    def _publish_ack(self, client, userdata, mid, reason, properties):
        self.acks.put((mid, not reason.is_failure))

    def _message(self, client, userdata, message):
        if not self.config.crop_enabled or message.topic != self.config.topic('crop_request') or message.retain:
            return
        if len(message.payload) > 4096:
            LOG.warning('oversized crop request ignored')
            return
        try:
            self.requests.put_nowait(message.payload)
        except queue.Full:
            LOG.warning('crop request queue full')

    def start(self):
        self.client.connect_async(self.config.host, self.config.port, keepalive=30)
        self.client.loop_start()
        self.thread.start()

    def _run(self):
        pending, info = None, None
        while not self.stopping.wait(0.1):
            if not self.connected.is_set():
                continue
            try:
                if pending is None:
                    pending = self.store.peek()
                if pending:
                    if info is None:
                        info = self.client.publish(self.config.topic('event'), json.dumps(pending, ensure_ascii=False), qos=1)
                        LOG.info('MQTT publish event_id=%s rc=%s', pending['event_id'], info.rc)
                        # Paho retains QoS1 messages even across disconnects. Keep info to
                        # avoid repeatedly queueing the same event in its in-memory queue.
                        if info.rc not in (0, 4):
                            info = None
                            self.stopping.wait(1)
                            continue
                    # Callback queue handles PUBACK arriving before publish() returns,
                    # and rc=NO_CONN messages that Paho queued before reconnection.
                    acknowledged = False
                    while True:
                        try:
                            mid, success = self.acks.get_nowait()
                        except queue.Empty:
                            break
                        if mid == info.mid and success:
                            acknowledged = True
                    if acknowledged:
                        self.store.acknowledge(pending['event_id'])
                        LOG.info('MQTT PUBACK event_id=%s', pending['event_id'])
                        pending, info = None, None
                else:
                    while not self.acks.empty():
                        self.acks.get_nowait()
                if self.crops:
                    try:
                        payload = self.requests.get_nowait()
                    except queue.Empty:
                        continue
                    response = self.crops.response(payload)
                    if response:
                        result = self.client.publish(self.config.topic('crop'), json.dumps(response), qos=1)
                        LOG.info('crop response queued rc=%s', result.rc)
                    else:
                        LOG.warning('crop unavailable/expired/event mismatch')
            except Exception:
                LOG.exception('MQTT/outbox error; durable events retained')
                self.stopping.wait(1)

    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.connected.is_set():
            try:
                info = self.client.publish(self.status_topic, json.dumps({'state':'offline', 'ts':now()}), qos=1, retain=True)
                info.wait_for_publish(timeout=2)
                LOG.info('MQTT graceful offline puback=%s ts=%s', info.is_published(), now())
            except Exception:
                LOG.exception('offline publication failed; LWT remains fallback')
        self.client.disconnect()
        self.client.loop_stop()
