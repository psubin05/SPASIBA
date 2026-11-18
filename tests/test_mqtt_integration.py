"""Real TLS/Mosquitto tests. Set SPASIBA_TEST_MOSQUITTO to a broker executable."""
import json
import os
from pathlib import Path
import queue
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from collections import deque
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from edge_cloud.config import Config
from edge_cloud.runtime import EdgeRuntime

BROKER=os.getenv('SPASIBA_TEST_MOSQUITTO')


def wait_until(predicate, timeout=12):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('condition timed out')


@unittest.skipUnless(BROKER,'set SPASIBA_TEST_MOSQUITTO for real TLS broker tests')
class MQTTIntegrationTests(unittest.TestCase):
    def setUp(self):
        import paho.mqtt.client as mqtt
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.key=self.root/'server.key'
        self.cert=self.root/'server.crt'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(self.key),'-out',str(self.cert),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            self.port=sock.getsockname()[1]
        self.conf=self.root/'mosquitto.conf'
        self.conf.write_text(f'persistence true\npersistence_location {self.root}/\nlistener {self.port} 127.0.0.1\nallow_anonymous true\ncertfile {self.cert}\nkeyfile {self.key}\n')
        self.log=(self.root/'broker.log').open('w')
        self.broker=None
        self.start_broker()
        self.messages=queue.Queue()
        self.observer=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='test-observer',clean_session=False)
        self.observer.tls_set_context(ssl.create_default_context(cafile=str(self.cert)))
        self.observer.on_connect=lambda c,u,f,r,p:c.subscribe('spasiba/#',qos=1)
        self.observer.on_message=lambda c,u,m:self.messages.put((m.topic,json.loads(m.payload),m.qos,m.retain))
        self.observer.connect('localhost',self.port,30)
        self.observer.loop_start()
        wait_until(self.observer.is_connected)
        subscribed=[]
        self.observer.on_subscribe=lambda *args:subscribed.append(True)
        self.observer.subscribe('spasiba/#',qos=1)
        wait_until(lambda:subscribed)
        self.config=Config(zone_id='B2-A',camera_id='CAM-B2-01',host='localhost',port=self.port,ca=str(self.cert),database=str(self.root/'events.sqlite3'),single_slot='B2-A-03',publish_on_consensus=True)
        self.runtime=None
    def start_broker(self):
        self.broker=subprocess.Popen([BROKER,'-c',str(self.conf)],stdout=self.log,stderr=self.log)
        def ready():
            if self.broker.poll() is not None:
                raise AssertionError('broker failed: '+(self.root/'broker.log').read_text())
            try:
                with socket.create_connection(('127.0.0.1',self.port),timeout=.2):
                    return True
            except OSError:
                return False
        wait_until(ready)
    def stop_broker(self):
        if self.broker and self.broker.poll() is None:
            self.broker.terminate()
            self.broker.wait(timeout=5)
    def tearDown(self):
        if self.runtime:
            self.runtime.close()
        self.observer.disconnect()
        self.observer.loop_stop()
        self.stop_broker()
        self.log.close()
        self.temp.cleanup()
    def event(self,plate='12가3456',crop=None):
        result={'bbox':[0,0,100,30]}
        if crop is not None:
            result['crop']=crop
        track=SimpleNamespace(readings=deque([(plate,.9)]*5,maxlen=10))
        return self.runtime.observe([(result,track)])[0]
    def message(self,suffix,predicate=lambda payload:True,timeout=12):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            try:
                row=self.messages.get(timeout=.2)
            except queue.Empty:
                continue
            if row[0].endswith('/'+suffix) and predicate(row[1]):
                return row
        self.fail('missing MQTT message '+suffix)
    def test_tls_qos1_puback_and_retained_online_offline(self):
        self.runtime=EdgeRuntime(self.config)
        wait_until(self.runtime.transport.connected.is_set)
        self.message('status',lambda x:x['state']=='online' and 'ts' in x)
        event=self.event()
        message=self.message('event')
        self.assertEqual(message[1]['event_id'],event['event_id'])
        self.assertEqual(message[2],1)
        wait_until(lambda:self.runtime.store.count()==0)
        self.assertEqual(self.runtime.observe([({'bbox':[0,0,1,1]},SimpleNamespace(readings=[('12가3456',.9)]*5))]),[])
        self.runtime.close()
        self.runtime=None
        self.message('status',lambda x:x['state']=='offline' and 'ts' in x)
        self.observer.subscribe(self.config.topic('status'),qos=1)
        retained=self.message('status',lambda x:x['state']=='offline')
        self.assertTrue(retained[3])
    def test_disconnect_reconnect_same_event_id(self):
        self.runtime=EdgeRuntime(self.config)
        wait_until(self.runtime.transport.connected.is_set)
        self.stop_broker()
        wait_until(lambda:not self.runtime.transport.connected.is_set())
        event=self.event()
        self.assertEqual(self.runtime.store.count(),1)
        self.start_broker()
        wait_until(self.runtime.transport.connected.is_set)
        wait_until(lambda:self.runtime.store.count()==0)
        self.assertEqual(self.message('event')[1]['event_id'],event['event_id'])
    def test_process_restart_recovers_outbox(self):
        self.stop_broker()
        self.runtime=EdgeRuntime(self.config)
        event=self.event()
        self.runtime.close()
        self.runtime=None
        self.start_broker()
        self.runtime=EdgeRuntime(self.config)
        wait_until(lambda:self.runtime.store.count()==0)
        self.assertEqual(self.message('event')[1]['event_id'],event['event_id'])
    def test_crop_request_response(self):
        import numpy as np
        self.config.crop_enabled=True
        self.runtime=EdgeRuntime(self.config)
        wait_until(self.runtime.transport.connected.is_set)
        event=self.event(crop=np.zeros((30,100,3),dtype=np.uint8))
        self.message('event')
        req=dict(request_id='r-1',event_id=event['event_id'],slot_id=event['slot_id'])
        info=self.observer.publish(self.config.topic('crop_request'),json.dumps(req),qos=1)
        info.wait_for_publish(3)
        response=self.message('crop')[1]
        self.assertEqual(response['request_id'],'r-1')
        self.assertTrue(response['image_jpeg_base64'].startswith('/9j/'))
    def test_lwt_abnormal_process_exit(self):
        # A separate process connects using the actual transport, then exits without cleanup.
        conf=self.root/'edge.json'
        conf.write_text(json.dumps(dict(zone_id=self.config.zone_id,camera_id=self.config.camera_id,host='localhost',port=self.port,ca=str(self.cert),database=str(self.root/'child.sqlite3'))))
        code="from edge_cloud.runtime import EdgeRuntime; from edge_cloud.config import Config; import sys,time,os; r=EdgeRuntime(Config.load(sys.argv[1])); deadline=time.monotonic()+10\nwhile not r.transport.connected.is_set() and time.monotonic()<deadline: time.sleep(.05)\ntime.sleep(.3); os._exit(0 if r.transport.connected.is_set() else 2)"
        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
        child=subprocess.run([sys.executable,'-c',code,str(conf)],env=env,timeout=15)
        self.assertEqual(child.returncode,0)
        self.message('status',lambda x:x['state']=='online')
        message=self.message('status',lambda x:x['state']=='offline')
        self.assertNotIn('ts',message[1])
    def test_username_password_authentication(self):
        import shutil
        password_tool=shutil.which('mosquitto_passwd') or str(Path(BROKER).parent.parent/'bin'/'mosquitto_passwd')
        self.stop_broker()
        self.observer.disconnect()
        self.observer.loop_stop()
        password_file=self.root/'passwords'
        subprocess.run([password_tool,'-b','-c',str(password_file),'test-edge','test-only-password'],check=True)
        self.conf.write_text(self.conf.read_text().replace('allow_anonymous true',f'allow_anonymous false\npassword_file {password_file}'))
        self.start_broker()
        self.config.username='test-edge'
        self.config.password='test-only-password'
        self.runtime=EdgeRuntime(self.config)
        wait_until(self.runtime.transport.connected.is_set)
        self.event()
        wait_until(lambda:self.runtime.store.count()==0)
        self.runtime.close()
        self.config.password='incorrect-test-password'
        self.runtime=EdgeRuntime(self.config)
        time.sleep(1)
        self.assertFalse(self.runtime.transport.connected.is_set())
    def test_untrusted_ca_does_not_drain_outbox(self):
        self.config.ca=None  # self-signed broker must be rejected by system trust roots
        self.runtime=EdgeRuntime(self.config)
        self.event()
        time.sleep(2)
        self.assertFalse(self.runtime.transport.connected.is_set())
        self.assertEqual(self.runtime.store.count(),1)

if __name__=='__main__':
    unittest.main()
