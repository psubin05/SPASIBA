import json
from pathlib import Path
import sys
import tempfile
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from edge_cloud.config import Config
from edge_cloud.events import consensus, normalize_plate
from edge_cloud.runtime import EdgeRuntime, optional_runtime
from edge_cloud.slots import Occupancy, SlotResolver
from edge_cloud.crops import CropCache, jpeg_bytes

class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(zone_id='B2-A',camera_id='CAM-B2-01',database=self.temp.name+'/events.sqlite3',single_slot='B2-A-03',publish_on_consensus=True)
        self.runtime = EdgeRuntime(self.config,network=False)
    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()
    def pairs(self,plate='12가3456',count=5):
        return [({'bbox':[10,10,100,50]},SimpleNamespace(readings=deque([(plate,.9)]*count,maxlen=10)))]
    def test_normalization(self):
        self.assertEqual(normalize_plate('서울 １２-가·３４５６'),'서울12가3456')
        self.assertIsNone(consensus([('garbage12가3456',.9)]*5))
        self.assertIsNotNone(consensus([('서울12가3456',.9)]*5))
    def test_votes_frames_last_ten_tie(self):
        self.assertIsNone(consensus([('12가3456',.9)]*9+[('34나5678',.8)]*5))
        self.assertEqual(consensus([('12가3456',.9)]*5+[('34나5678',.8)]*2),('12가3456',5,7))
        self.assertIsNone(consensus([('12가3456',.9)]*4))
    def test_uuid_time_json(self):
        import uuid
        from datetime import datetime
        event=self.runtime.observe(self.pairs())[0]
        self.assertEqual(uuid.UUID(event['event_id']).version,4)
        self.assertIsNotNone(datetime.fromisoformat(event['recognized_at']).tzinfo)
        self.assertEqual(json.loads(json.dumps(event))['kind'],'confirm')
    def test_repeat_occlusion_and_changed_plate(self):
        self.assertEqual(len(self.runtime.observe(self.pairs())),1)
        self.runtime.observe([])
        self.assertEqual(self.runtime.observe(self.pairs()),[])
        self.assertEqual(len(self.runtime.observe(self.pairs('34나5678'))),1)
        self.assertEqual(self.runtime.store.count(),2)
    def test_restart_same_id_dedup_and_ack(self):
        event=self.runtime.observe(self.pairs())[0]
        self.runtime.close()
        self.runtime=EdgeRuntime(self.config,network=False)
        self.assertEqual(self.runtime.store.peek()['event_id'],event['event_id'])
        self.assertEqual(self.runtime.observe(self.pairs()),[])
        self.runtime.store.acknowledge(event['event_id'])
        self.assertEqual(self.runtime.store.count(),0)
        self.assertEqual(self.runtime.observe(self.pairs()),[])
    def test_legacy_camera_outbox_is_retained(self):
        from edge_cloud.transport import MQTTTransport
        from unittest.mock import Mock

        old_event = self.runtime.observe(self.pairs())[0]
        self.config.host = '127.0.0.1'
        self.config.tls = False
        self.config.camera_id = 'CAM-B2-02'
        client = Mock()
        transport = MQTTTransport(self.config, self.runtime.store, client=client)
        with self.assertRaisesRegex(ValueError, 'Outbox camera ID'):
            transport.start()
        client.connect_async.assert_not_called()
        self.assertEqual(self.runtime.store.peek(), old_event)
    def test_explicit_empty_new_session(self):
        first=self.runtime.observe(self.pairs())[0]
        self.runtime.store.set_occupancy(self.config.single_slot,Occupancy.EMPTY)
        self.assertEqual(self.runtime.observe(self.pairs()),[])
        self.runtime.store.set_occupancy(self.config.single_slot,Occupancy.OCCUPIED)
        self.assertNotEqual(first['event_id'],self.runtime.observe(self.pairs())[0]['event_id'])
    def test_unknown_holds(self):
        self.config.publish_on_consensus=False
        self.assertEqual(self.runtime.observe(self.pairs()),[])
        self.runtime.store.set_occupancy(self.config.single_slot,Occupancy.OCCUPIED)
        self.assertEqual(len(self.runtime.observe(self.pairs())),1)
    def test_missing_ambiguous_roi(self):
        self.config.single_slot=None
        self.assertEqual(self.runtime.observe(self.pairs()),[])
        polygon=[[0,0],[200,0],[200,100],[0,100]]
        self.config.rois={'B2-A-01':polygon,'B2-A-02':polygon}
        self.assertEqual(self.runtime.observe(self.pairs()),[])
        self.config.rois.pop('B2-A-02')
        self.assertEqual(SlotResolver(self.config).resolve([10,10,100,50]),'B2-A-01')
    def test_multiple_tracks_hold(self):
        self.assertEqual(self.runtime.observe(self.pairs()+self.pairs('34나5678')),[])
    def test_unconfirmed_second_track_and_stale_consensus_hold(self):
        self.assertEqual(self.runtime.observe(self.pairs()+self.pairs('34나5678',1)),[])
        pairs=self.pairs()
        pairs[0][0]['plate_text']='34나5678'
        self.assertEqual(self.runtime.observe(pairs),[])
        pairs[0][0]['format_valid']=False
        self.assertEqual(self.runtime.observe(pairs),[])
    def test_full_queue_no_loss(self):
        self.runtime.store.max_pending=1
        event=self.runtime.observe(self.pairs())[0]
        with self.assertRaises(RuntimeError):
            self.runtime.observe(self.pairs('34나5678'))
        self.runtime.store.acknowledge(event['event_id'])
        self.assertEqual(len(self.runtime.observe(self.pairs('34나5678'))),1)
    def test_invalid_settings(self):
        for kw in ({'port':0},{'host':'example.com','tls':False},{'min_votes':11},{'ca':'/not-found'},{'single_slot':'B1-A-3'},{'tls':'false'},{'camera_id':'CAM-B2-A-01'},{'rois':{'B2-A-03':[[0,0]]}}):
            with self.assertRaises(ValueError):
                Config(**{**dict(zone_id='B2-A',camera_id='CAM-B2-01'),**kw})
    def test_bad_config_keeps_ocr(self):
        with self.assertLogs('edge_cloud.runtime',level='ERROR'):
            self.assertIsNone(optional_runtime(SimpleNamespace(mqtt=True,edge_config='/missing')))
    def test_missing_broker_outbox_works(self):
        with self.assertLogs('edge_cloud.runtime',level='ERROR'):
            other=EdgeRuntime(self.config)
        try:
            self.assertEqual(len(other.observe(self.pairs())),1)
        finally:
            other.close()
    def test_puback_required_and_early_no_connection_ack(self):
        from unittest.mock import Mock
        import time
        from edge_cloud.transport import MQTTTransport
        for early_ack in (False,True):
            self.runtime.store.set_occupancy(self.config.single_slot,Occupancy.EMPTY)
            self.runtime.store.set_occupancy(self.config.single_slot,Occupancy.OCCUPIED)
            event=self.runtime.observe(self.pairs())[0]
            client=Mock()
            self.config.host='127.0.0.1'
            self.config.tls=False
            transport=MQTTTransport(self.config,self.runtime.store,client=client)
            def publish(*args,**kwargs):
                if early_ack:
                    client.on_publish(client,None,42,SimpleNamespace(is_failure=False),None)
                return SimpleNamespace(mid=42,rc=4 if early_ack else 0)
            client.publish.side_effect=publish
            transport.connected.set()
            transport.thread.start()
            try:
                if not early_ack:
                    time.sleep(.3)
                    self.assertEqual(self.runtime.store.count(),1)
                    client.on_publish(client,None,42,SimpleNamespace(is_failure=False),None)
                deadline=time.monotonic()+3
                while self.runtime.store.count() and time.monotonic()<deadline:
                    time.sleep(.05)
                self.assertEqual(self.runtime.store.count(),0)
                self.assertEqual(client.publish.call_count,1)
            finally:
                transport.stopping.set()
                transport.thread.join(3)
    def test_crop_limits_binding_expiry(self):
        import cv2
        import numpy as np
        crop=np.random.default_rng(7).integers(0,256,(900,1400,3),dtype=np.uint8)
        encoded=jpeg_bytes(crop)
        self.assertLessEqual(len(encoded),100000)
        decoded=cv2.imdecode(np.frombuffer(encoded,dtype=np.uint8),cv2.IMREAD_COLOR)
        self.assertLessEqual(max(decoded.shape[:2]),640)
        event=self.runtime.observe(self.pairs())[0]
        cache=CropCache(120)
        cache.put(event,crop)
        request=dict(request_id='r-1',event_id=event['event_id'],slot_id=event['slot_id'])
        self.assertIsNotNone(cache.response(json.dumps(request)))
        self.assertIsNone(cache.response(json.dumps({**request,'event_id':'other'})))
        with patch('edge_cloud.crops.time.monotonic',return_value=10**20):
            self.assertIsNone(cache.response(json.dumps(request)))
        with self.assertRaises(ValueError):
            cache.response('{}')

if __name__=='__main__':
    unittest.main()
