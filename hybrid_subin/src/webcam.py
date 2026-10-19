from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import cv2

from detector import PlateDetector
from paddle_ocr import SubinPaddleOCR
from pipeline import HybridPlateReader
from tracking import Tracker
from visualization import draw_results


def main():
    parser = argparse.ArgumentParser(description="soogguang detection + subin OCR webcam")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fourcc", default="MJPG", help="웹캠 포맷; 1080p는 보통 MJPG 필요")
    parser.add_argument("--process-every", type=int, default=5)
    parser.add_argument("--det-size", type=int, default=960, choices=(640, 960, 1280))
    parser.add_argument("--det-conf", type=float, default=0.25)
    parser.add_argument("--tile-detect", action="store_true", help="겹치는 2x2 타일로 먼 번호판 재검출")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ocr-device", default="cpu")
    parser.add_argument("--robust", action="store_true")
    parser.add_argument("--min-votes", type=int, default=2)
    parser.add_argument("--output", default="outputs/webcam")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()
    if args.process_every < 1:
        parser.error("--process-every는 1 이상이어야 합니다")

    print("plate_v3와 PaddleOCR 모델을 불러오는 중입니다...")
    reader = HybridPlateReader(
        PlateDetector(confidence=args.det_conf, image_size=args.det_size, device=args.device, tiled=args.tile_detect),
        SubinPaddleOCR(args.ocr_device, args.robust),
    )
    tracker = Tracker(max_age=max(20, args.process_every * 6))
    capture = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    if len(args.fourcc) == 4:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not capture.isOpened():
        raise SystemExit(f"카메라 {args.camera}을 열 수 없습니다. --camera 1도 확인하세요.")
    actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"카메라 실제 해상도: {actual_width}x{actual_height} (요청 {args.width}x{args.height})")

    results, frame_index = [], 0
    previous = ()
    print("번호판을 보여주세요. q/ESC 종료, s 화면 저장")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % args.process_every == 0:
                current = reader(frame)
                results = []
                for result, track in tracker.update(current, frame_index):
                    stable = track.best(args.min_votes)
                    item = dict(result)
                    if stable:
                        item["display_text"], item["ocr_confidence"], item["votes"] = stable
                    else:
                        # Show a valid instant reading immediately; votes indicate
                        # whether it is confirmed across frames.
                        item["display_text"] = result["plate_text"] if result["format_valid"] else ""
                        item["votes"] = int(result["format_valid"])
                    item["track_id"] = track.track_id
                    results.append(item)
                summary = tuple(item["display_text"] for item in results)
                if summary and summary != previous:
                    print(f"[{datetime.now():%H:%M:%S}] " + ", ".join(
                        f"{item['display_text'] or '(미인식)'} (D {item['detection_confidence']:.2f}, "
                        f"OCR {item['ocr_confidence']:.2f}, votes {item['votes']}, "
                        f"crop {item['crop_width']}x{item['crop_height']}, "
                        f"track {item['track_id']}, {item['method']}/{item['preprocessing']}, "
                        f"raw={item['raw_text']!r})"
                        for item in results
                    ))
                previous = summary
            shown = draw_results(frame, results)
            if not args.headless:
                cv2.imshow("SPASIBA hybrid: plate_v3 + Subin PaddleOCR", shown)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if key == ord("s"):
                    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
                    path = output / f"webcam_{datetime.now():%Y%m%d_%H%M%S}.jpg"
                    cv2.imwrite(str(path), shown); print(f"저장: {path}")
            frame_index += 1
            if args.max_frames and frame_index >= args.max_frames:
                break
    finally:
        capture.release()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
