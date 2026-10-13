"""라즈베리파이용 번호판 읽기 — onnxruntime + OpenCV + numpy만 사용 (PyTorch·Paddle 불필요)

  python pi_reader.py <사진 폴더>                         # 사진마다 읽은 번호 출력
  python pi_reader.py <사진 폴더> --bench --size 416       # 단계별 속도 측정
  python pi_reader.py --camera 0 --bench                   # 카메라 프레임으로 속도 측정

ocr/plate_reader.py(서버용)와 같은 일을 한다: ① 검출 → ② 줄 검출 → 펴기 → ③ 인식
모델은 deploy/models/ (export_onnx.py로 생성)
"""
import argparse, json, sys, time
from pathlib import Path
import cv2, numpy as np, onnxruntime as ort

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ocr"))
from make_ocr_v1 import MARGIN, clean_boxes, group_lines, imread, unfold   # noqa: E402  (torch·paddle 안 씀)

MODELS = HERE / "models"
TOPK = 3


def session(path, threads):
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


class PiPlateReader:
    def __init__(self, size=640, threads=4, det_conf=0.25):
        self.size, self.det_conf = size, det_conf
        self.det = session(MODELS / f"plate_{size}.onnx", threads)
        self.line = session(MODELS / "line_det.onnx", threads)
        self.ocr = session(MODELS / "ocr_v1.onnx", threads)
        meta = json.loads((MODELS / "ocr_v1.json").read_text(encoding="utf-8"))
        self.tokens, self.oh, self.ow = meta["tokens"], meta["h"], meta["w"]
        self.times = {"① 검출": [], "② 줄 검출": [], "③ 인식": []}

    # ① 번호판 검출 (YOLO, letterbox → NMS)
    def detect(self, img):
        t = time.perf_counter()
        h, w = img.shape[:2]
        r = min(self.size / h, self.size / w)
        nw, nh = round(w * r), round(h * r)
        left, top = round((self.size - nw) / 2 - 0.1), round((self.size - nh) / 2 - 0.1)
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255
        pred = self.det.run(None, {self.det.get_inputs()[0].name: x})[0][0].T   # (N, 5) cx cy w h score
        pred = pred[pred[:, 4] > self.det_conf]
        boxes = np.stack([pred[:, 0] - pred[:, 2] / 2, pred[:, 1] - pred[:, 3] / 2, pred[:, 2], pred[:, 3]], 1)
        keep = cv2.dnn.NMSBoxes(boxes.tolist(), pred[:, 4].tolist(), self.det_conf, 0.7) if len(pred) else []
        out = []
        for i in np.array(keep).flatten():
            x1, y1, bw, bh = (boxes[i] - [left, top, 0, 0]) / r
            mx, my = bw * MARGIN, bh * MARGIN
            box = (int(max(0, x1 - mx)), int(max(0, y1 - my)), int(min(w, x1 + bw + mx)), int(min(h, y1 + bh + my)))
            out.append({"box": box, "det_conf": float(pred[i, 4]), "crop": img[box[1]:box[3], box[0]:box[2]]})
        self.times["① 검출"].append(time.perf_counter() - t)
        return out

    # ② 줄 검출 (PP-OCR det → DB 후처리 → ocr/make_ocr_v1.py와 같은 정리 규칙)
    def find_lines(self, plate):
        t = time.perf_counter()
        h, w = plate.shape[:2]
        s = 320 / w
        small = cv2.resize(plate, (320, max(32, int(h * s))))
        sh, sw = small.shape[:2]
        rh, rw = max(32, round(sh / 32) * 32), max(32, round(sw / 32) * 32)
        x = (cv2.resize(small, (rw, rh)).astype(np.float32) / 255 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        prob = self.line.run(None, {self.line.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
        contours, _ = cv2.findContours((prob > 0.3).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        raw = []
        for c in contours:
            if len(c) < 3:
                continue
            (cx, cy), (bw, bh), ang = cv2.minAreaRect(c)
            if min(bw, bh) < 3:
                continue
            mask = np.zeros_like(prob, np.uint8)
            cv2.fillPoly(mask, [c], 1)
            if prob[mask == 1].mean() < 0.6:
                continue
            d = bw * bh * 1.5 / (2 * (bw + bh))                    # unclip 1.5
            pts = cv2.boxPoints(((cx, cy), (bw + 2 * d, bh + 2 * d), ang))
            (x1, y1), (x2, y2) = pts.min(0), pts.max(0)
            x1, x2 = x1 * sw / rw / s, x2 * sw / rw / s            # → 번호판 crop 좌표
            y1, y2 = y1 * sh / rh / s, y2 * sh / rh / s
            if (x2 - x1) * (y2 - y1) > 0.01 * w * h:
                raw.append((max(0, x1), max(0, y1), min(w, x2), min(h, y2)))
        lines = group_lines(clean_boxes(raw))
        self.times["② 줄 검출"].append(time.perf_counter() - t)
        return lines

    # ③ 인식 (펴기 → CTC greedy → 글자별 상위 후보)
    def recognize(self, plate, lines):
        t = time.perf_counter()
        img = unfold(plate, lines[:2] if len(lines) >= 2 else lines, self.oh)
        nw = min(self.ow, max(8, round(img.shape[1] * self.oh / img.shape[0])))
        canvas = np.full((self.oh, self.ow, 3), 127, np.uint8)
        canvas[:, :nw] = cv2.resize(img, (nw, self.oh))
        x = ((canvas.astype(np.float32) / 255 - 0.5) / 0.5).transpose(2, 0, 1)[None]
        probs = np.exp(self.ocr.run(None, {"image": x})[0][0])    # (T, C)
        text, conf, char_probs, prev = "", 1.0, [], 0
        for step, s in enumerate(probs.argmax(-1)):
            if s != prev and s != 0:
                order = [i for i in np.argsort(-probs[step]) if i != 0][:TOPK]
                char_probs.append([(self.tokens[i - 1], round(float(probs[step, i]), 4)) for i in order])
                text += self.tokens[s - 1]; conf *= float(probs[step, s])
            prev = s
        self.times["③ 인식"].append(time.perf_counter() - t)
        return {"text": text, "conf": conf, "n_lines": len(lines), "char_probs": char_probs}

    def __call__(self, img):
        out = []
        for p in self.detect(img):
            if p["crop"].size:
                out.append({**p, **self.recognize(p["crop"], self.find_lines(p["crop"]))})
        return out


def frames(a):
    if a.camera is not None:
        cap = cv2.VideoCapture(a.camera)
        for i in range(a.frames):
            ok, f = cap.read()
            if not ok:
                break
            yield f"frame{i}", f
        cap.release()
    else:
        for p in sorted(q for q in Path(a.src).iterdir() if q.suffix.lower() in (".jpg", ".jpeg", ".png")):
            yield p.name, imread(p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?")
    ap.add_argument("--camera", type=int)
    ap.add_argument("--frames", type=int, default=50)
    ap.add_argument("--size", type=int, default=640, choices=[640, 416, 320])
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--bench", action="store_true")
    a = ap.parse_args()
    reader = PiPlateReader(a.size, a.threads)
    total, n_img, n_plate = [], 0, 0
    for name, img in frames(a):
        t = time.perf_counter()
        plates = reader(img)
        total.append(time.perf_counter() - t)
        n_img += 1; n_plate += len(plates)
        if not a.bench:
            print(f"{name}: " + (", ".join(f"{p['text']}({p['conf']:.2f})" for p in plates) or "번호판 없음"))
    if a.bench and n_img:
        warm = total[1:] or total                                  # 첫 프레임은 준비 시간이 섞여서 뺌
        print(f"입력 {a.size}, 스레드 {a.threads}, 사진 {n_img}장, 번호판 {n_plate}개")
        for k, v in reader.times.items():
            if v:
                print(f"  {k:<8} 평균 {np.mean(v) * 1000:7.1f} ms  ({len(v)}회)")
        print(f"  사진 1장 전체 평균 {np.mean(warm) * 1000:7.1f} ms  → 약 {1 / np.mean(warm):.1f}장/초")
