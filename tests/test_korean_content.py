"""Check actual saved UTF-8 labels, not only API status codes."""

from html.parser import HTMLParser
import json
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from server.legacy_app import create_app

ROOT = Path(__file__).resolve().parents[1]


class VisibleContent(HTMLParser):
    def __init__(self):
        super().__init__()
        self.labels = []

    def handle_data(self, data):
        self.labels.append(data)

    def handle_starttag(self, tag, attrs):
        self.labels.extend(value for key, value in attrs if key in ('placeholder', 'value', 'aria-label') and value)


class KoreanContentTests(unittest.TestCase):
    def test_saved_labels_and_sample_plate_are_intact(self):
        html = (ROOT / 'simulator/index.html').read_text(encoding='utf-8', errors='strict')
        parser = VisibleContent()
        parser.feed(html)
        for label in parser.labels:
            self.assertNotIn('?', label)
            self.assertNotIn('\ufffd', label)
        for text in ('내 차 찾기', 'QR 출발 위치', '차량 검색 · 경로 안내', '차단기 인식 결과 저장', '12가3456'):
            self.assertIn(text, html)

    def test_http_html_and_map_preserve_korean(self):
        with TestClient(create_app()) as client:
            response = client.get('/simulator')
            self.assertIn('charset=utf-8', response.headers['content-type'])
            self.assertIn('내 차 찾기', response.content.decode('utf-8'))
            self.assertEqual(client.get('/qr/QR-B2-ENT1').json()['name'], '출입구 A')
            labels = client.get('/simulator/layout').json()['layout']['camera_mounts']
            self.assertEqual(labels[0]['label'], 'CAM A (임시)')
