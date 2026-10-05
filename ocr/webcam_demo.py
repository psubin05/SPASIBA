"""Local browser webcam demo for the current license-plate OCR pipeline."""

import argparse
import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

from PIL import Image, UnidentifiedImageError

from evaluate import PLATE_PATTERN, extract_plate, make_model, predict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(PROJECT_ROOT / "data/.paddlex"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
PAGE = Path(__file__).with_name("webcam_demo.html")
MAX_IMAGE_BYTES = 2_000_000


class Handler(BaseHTTPRequestHandler):
    model = None
    model_lock = Lock()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        body = PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/recognize":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "Invalid image length"}, 400)
            return
        if not 0 < length <= MAX_IMAGE_BYTES:
            self.send_json({"error": "Image must be at most 2 MB"}, 413)
            return
        try:
            with Image.open(io.BytesIO(self.rfile.read(length))) as incoming:
                image = incoming.convert("RGB")
            if image.width * image.height > 4_000_000:
                self.send_json({"error": "Image is too large"}, 413)
                return
            with self.model_lock:
                raw, score = predict(self.model, image, "pipeline")
            candidate = extract_plate(raw)
            plate = candidate if PLATE_PATTERN.fullmatch(candidate) else ""
            self.send_json({"plate": plate, "raw": raw, "confidence": round(score, 3)})
        except (UnidentifiedImageError, OSError):
            self.send_json({"error": "Invalid image"}, 400)
        except Exception as exc:
            self.send_json({"error": f"OCR failed: {exc}"}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.model = make_model("pipeline", "cpu")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Open http://localhost:{args.port} in the browser with the webcam", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
