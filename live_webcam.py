#!/usr/bin/env python3
"""실시간 한국 번호판 인식. 카메라 또는 동영상 입력을 지원합니다."""
import argparse
import csv
import os
import sys
import threading
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lp_engine import KoreanLP, Voter, draw_text, load_font, normalize  # noqa: E402


def open_source(src, w, h):
    is_file = not str(src).isdigit()
    if is_file:
        cap = cv2.VideoCapture(src)
    else:
        idx = int(src)
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if sys.platform.startswith("win") else cv2.VideoCapture(idx)
        if w and h:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    return cap, is_file


class Worker(threading.Thread):
    """Keep camera display responsive by inferring only the latest submitted frame."""
    def __init__(self, eng):
        super().__init__(daemon=True)
        self.eng, self.lock = eng, threading.Lock()
        self.frame, self.result, self.ms, self.seq, self.done_seq = None, [], 0.0, 0, 0
        self.stop = False

    def submit(self, frame):
        with self.lock:
            self.frame, self.seq = frame, self.seq + 1

    def run(self):
        last = 0
        while not self.stop:
            with self.lock:
                frame, seq = self.frame, self.seq
            if frame is None or seq == last:
                time.sleep(0.005)
                continue
            last = seq
            t0 = time.time()
            try:
                dets = self.eng.infer(frame)
            except Exception as exc:
                print("[추론 오류]", exc)
                dets = []
            with self.lock:
                self.result, self.ms, self.done_seq = dets, (time.time() - t0) * 1000, seq


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="EasyKoreanLpDetector 폴더")
    ap.add_argument("--stage", default="plate", choices=["plate", "car+plate"])
    ap.add_argument("--cam", default="0", help="카메라 번호")
    ap.add_argument("--source", default=None, help="카메라 대신 동영상 파일 경로")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--window", type=int, default=10, help="투표에 쓰는 최근 프레임 수")
    ap.add_argument("--min-votes", type=int, default=3, help="확정에 필요한 최소 동일 결과 수")
    ap.add_argument("--conf", type=float, default=0.25, help="번호판 탐지 최소 신뢰도")
    ap.add_argument("--every", type=int, default=3, help="동영상 파일 N프레임마다 추론")
    ap.add_argument("--save-dir", default="live_log")
    ap.add_argument("--no-display", action="store_true", help="창 없이 실행")
    ap.add_argument("--max-frames", type=int, default=0, help="0=무제한")
    ap.add_argument("--yolov5", default=None)
    args = ap.parse_args()
    if args.window < 1 or args.min_votes < 1 or args.every < 1:
        ap.error("--window, --min-votes, --every must be positive")

    print("모델 로드 중...")
    eng = KoreanLP(args.repo, stage=args.stage, min_det_conf=args.conf, yolov5_dir=args.yolov5)
    font_s, font_l = load_font(os.path.abspath(args.repo), 26), load_font(os.path.abspath(args.repo), 44)
    src = args.source if args.source is not None else args.cam
    cap, is_file = open_source(src, args.width, args.height)
    if not cap.isOpened():
        sys.exit(f"카메라/영상을 열 수 없습니다: {src}")

    os.makedirs(args.save_dir, exist_ok=True)
    log_path = os.path.join(args.save_dir, "events.csv")
    new_log = not os.path.exists(log_path)
    logf = open(log_path, "a", newline="", encoding="utf-8-sig")
    log = csv.writer(logf)
    if new_log:
        log.writerow(["time", "event", "text", "format_ok", "det_conf", "ocr_conf", "votes"])
    worker = None
    if not is_file:
        worker = Worker(eng)
        worker.start()
    voter = Voter(args.window, args.min_votes)
    confirmed, confirmed_at = None, 0.0
    last_dets, last_ms = [], 0.0
    vis, seen = None, 0
    t_prev, fps, n = time.time(), 0.0, 0
    print("시작했습니다. q 종료 / s 저장 / r 초기화")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            if args.max_frames and n > args.max_frames:
                break
            if is_file:
                if n % args.every == 0:
                    t0 = time.time()
                    last_dets = eng.infer(frame)
                    last_ms = (time.time() - t0) * 1000
                    new = True
                else:
                    new = False
            else:
                worker.submit(frame.copy())
                with worker.lock:
                    last_dets, last_ms, done = list(worker.result), worker.ms, worker.done_seq
                new = done != seen
                seen = done
            if new:
                best = next((d for d in last_dets if d.valid), None)
                voter.add(normalize(best.text) if best else None)
                result, votes = voter.result()
                if result and result != confirmed:
                    confirmed, confirmed_at = result, time.time()
                    print(f"[확정] {result} (최근 {args.window}프레임 중 {votes}회 일치)")
                    item = best if best and normalize(best.text) == result else last_dets[0]
                    log.writerow([time.strftime("%H:%M:%S"), "confirmed", result, int(item.valid),
                                  f"{item.det_conf:.2f}", f"{item.ocr_conf:.2f}", votes])
                    logf.flush()
            vis = frame.copy()
            for det in last_dets:
                x1, y1, x2, y2 = det.box
                col = (0, 200, 0) if det.valid else (0, 140, 255)
                cv2.rectangle(vis, (x1, y1), (x2, y2), col, 3)
                vis = draw_text(vis, f"{det.text} ({det.ocr_conf:.2f})", (x1, max(0, y1 - 38)), font_s,
                                (255, 255, 255), col)
            now = time.time()
            fps = 0.9 * fps + 0.1 / max(now - t_prev, 1e-6)
            t_prev = now
            cur = next(iter(last_dets), None)
            lines = [f"현재 인식: {cur.text if cur else '(번호판 없음)'}" +
                     (f"   [{'형식 OK' if cur.valid else '형식 불일치'}]" if cur else ""),
                     f"추론 {last_ms:.0f}ms | 화면 {fps:.0f}fps | 모드 {args.stage}"]
            vis = draw_text(vis, lines[0], (12, 10), font_s, (255, 255, 255), (60, 60, 60))
            vis = draw_text(vis, lines[1], (12, 48), font_s, (220, 220, 220), (60, 60, 60))
            if confirmed:
                fresh = (now - confirmed_at) < 3
                vis = draw_text(vis, f"확정: {confirmed}", (12, 92), font_l, (255, 255, 255),
                                (0, 150, 0) if fresh else (90, 90, 90))
            vis = draw_text(vis, "q 종료 | s 저장 | r 초기화", (12, vis.shape[0] - 40), font_s,
                            (255, 255, 255), (60, 60, 60))
            if not args.no_display:
                cv2.imshow("SPASIBA plate recognition", vis)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    voter, confirmed = Voter(args.window, args.min_votes), None
                    print("[초기화]")
                if key == ord("s"):
                    path = os.path.join(args.save_dir, time.strftime("snap_%H%M%S.jpg"))
                    ok2, buf = cv2.imencode(".jpg", vis)
                    if ok2:
                        buf.tofile(path)
                    log.writerow([time.strftime("%H:%M:%S"), "snapshot",
                                  cur.text if cur else "", int(cur.valid) if cur else "", "", "", ""])
                    logf.flush()
                    print("[저장]", path)
        if args.no_display and vis is not None:
            path = os.path.join(args.save_dir, "last_frame.jpg")
            ok2, buf = cv2.imencode(".jpg", vis)
            if ok2:
                buf.tofile(path)
            print("마지막 화면 저장:", path)
    finally:
        if worker:
            worker.stop = True
            worker.join(timeout=5)
        cap.release()
        logf.close()
        if not args.no_display:
            cv2.destroyAllWindows()
    print(f"종료. 최종 확정 결과: {confirmed or '(없음)'}   기록: {log_path}")


if __name__ == "__main__":
    main()
