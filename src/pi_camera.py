from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from pathlib import Path

import cv2

from detector import PlateDetector
from paddle_ocr import SubinPaddleOCR
from pipeline import HybridPlateReader
from tracking import Tracker
from visualization import draw_results
from edge_cloud.runtime import add_arguments, optional_runtime


def parse_args():
    parser = argparse.ArgumentParser(description="Raspberry Pi Camera + plate_v3 + Subin PaddleOCR")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--process-every", type=int, default=10)
    parser.add_argument("--det-size", type=int, default=640, choices=(640, 960, 1280))
    parser.add_argument("--det-conf", type=float, default=0.25)
    parser.add_argument("--detector-model", help="plate_v3.pt 경로; 기본값은 기존 soogguang 상대 경로")
    parser.add_argument("--tile-detect", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ocr-device", default="cpu")
    parser.add_argument("--robust", action="store_true")
    parser.add_argument("--min-votes", type=int, default=2)
    parser.add_argument("--display", action="store_true", help="Pi 데스크톱에 OpenCV 창 표시")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--output", default="outputs/pi_camera")
    add_arguments(parser)
    args = parser.parse_args()
    if args.process_every < 1:
        parser.error("--process-every는 1 이상이어야 합니다")
    return args


def configure_camera(args):
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise SystemExit(
            "Picamera2가 없습니다. Raspberry Pi OS에서 "
            "`sudo apt install python3-picamera2`를 실행하세요."
        ) from exc
    camera = Picamera2()
    config = camera.create_video_configuration(
        main={"size": (args.width, args.height), "format": "RGB888"},
        controls={"FrameRate": args.fps},
        buffer_count=4,
    )
    camera.configure(config)
    try:
        from libcamera import controls
        camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        autofocus = "continuous"
    except Exception:
        autofocus = "fixed/manual"
    camera.start()
    time.sleep(1.0)
    print(f"Pi Camera 해상도: {args.width}x{args.height}, FPS: {args.fps}, AF: {autofocus}")
    return camera


def main():
    args = parse_args()
    print("plate_v3와 PaddleOCR 모델을 불러오는 중입니다...")
    # PaddleOCR must initialize before torch (YOLO) loads; the reverse order segfaults on Raspberry Pi.
    ocr = SubinPaddleOCR(args.ocr_device, args.robust)
    reader = HybridPlateReader(
        PlateDetector(model_path=args.detector_model, confidence=args.det_conf, image_size=args.det_size,
                      device=args.device, tiled=args.tile_detect),
        ocr,
    )
    tracker = Tracker(max_age=max(30, args.process_every * 6))
    camera = configure_camera(args)
    edge = optional_runtime(args)
    output_dir = Path(args.output)
    frame_index, results, previous = 0, [], ()
    measured_fps = 0.0
    print("Pi Camera 인식 시작. Ctrl+C 종료" + (", q/ESC 종료, s 저장" if args.display else ""))
    try:
        while True:
            started = time.perf_counter()
            rgb = camera.capture_array("main")
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            if frame_index % args.process_every == 0:
                try:
                    current = reader(frame)
                except Exception:
                    logging.exception("OCR frame failed; retrying on next processing frame")
                    current = []
                pairs = tracker.update(current, frame_index)
                if edge:
                    try:
                        edge.observe(pairs)
                    except Exception:
                        logging.exception("Edge event deferred; OCR continues")
                results = []
                for result, track in pairs:
                    stable = track.best(args.min_votes)
                    item = dict(result)
                    if stable:
                        item["display_text"], item["ocr_confidence"], item["votes"] = stable
                    else:
                        item["display_text"] = result["plate_text"] if result["format_valid"] else ""
                        item["votes"] = int(result["format_valid"])
                    item["track_id"] = track.track_id
                    results.append(item)
                summary = tuple(item["display_text"] for item in results)
                if summary and summary != previous:
                    print(f"[{datetime.now():%H:%M:%S}] " + ", ".join(
                        f"{item['display_text'] or '(미인식)'} "
                        f"(D {item['detection_confidence']:.2f}, OCR {item['ocr_confidence']:.2f}, "
                        f"votes {item['votes']}, crop {item['crop_width']}x{item['crop_height']}, "
                        f"track {item['track_id']}, raw={item['raw_text']!r})" for item in results
                    ))
                previous = summary
            elapsed = max(time.perf_counter() - started, 1e-6)
            instant_fps = 1.0 / elapsed
            measured_fps = instant_fps if not measured_fps else measured_fps * 0.85 + instant_fps * 0.15
            if args.display:
                shown = draw_results(frame, results)
                status = f"Pi Camera FPS~{measured_fps:.1f} plates={len(results)} interval={args.process_every}"
                cv2.putText(shown, status, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(shown, status, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.imshow("SPASIBA Raspberry Pi Camera ALPR", shown)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if key == ord("s"):
                    output_dir.mkdir(parents=True, exist_ok=True)
                    path = output_dir / f"pi_{datetime.now():%Y%m%d_%H%M%S}.jpg"
                    cv2.imwrite(str(path), shown)
                    print(f"저장: {path}")
            frame_index += 1
            if args.max_frames and frame_index >= args.max_frames:
                break
    except KeyboardInterrupt:
        print("종료합니다.")
    finally:
        if edge:
            edge.close()
        camera.stop()
        camera.close()
        if args.display:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
