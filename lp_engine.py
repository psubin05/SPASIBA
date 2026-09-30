"""Reusable inference wrapper for EasyKoreanLpDetector."""
import os
import re
from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np

PLATE_SIZE = (224, 128)
CAR_CLASSES = [2, 3, 5, 7]
PLATE_RE = re.compile(r"^(?:[가-힣]{2})?\d{2,3}[가-힣]\d{4}$")


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def is_valid_format(text: str) -> bool:
    return bool(PLATE_RE.match(normalize(text)))


@dataclass
class Detection:
    box: tuple
    text: str
    ocr_conf: float
    det_conf: float
    valid: bool = False
    crop: np.ndarray = field(default=None, repr=False)


class KoreanLP:
    def __init__(self, repo_dir=".", stage="plate", device=None,
                 min_det_conf=0.25, gpu=None, yolov5_dir=None):
        if stage not in ("plate", "car+plate"):
            raise ValueError("stage must be 'plate' or 'car+plate'")
        self.repo = os.path.abspath(repo_dir)
        self.stage = stage
        self.min_det_conf = min_det_conf
        self.yolov5_dir = (os.path.abspath(yolov5_dir) if yolov5_dir else
                           (os.path.join(self.repo, "yolov5")
                            if os.path.isdir(os.path.join(self.repo, "yolov5")) else None))
        for need in ("lp_det.pt", os.path.join("lp_models", "models", "best_acc.pth")):
            if not os.path.exists(os.path.join(self.repo, need)):
                raise FileNotFoundError(
                    f"'{need}' 파일이 {self.repo} 에 없습니다. EasyKoreanLpDetector 저장소 폴더를 --repo 로 지정하세요.")
        self._load(gpu)

    def _load(self, gpu):
        import torch
        import easyocr

        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            self.car_m = None
            if self.stage == "car+plate":
                from ultralytics import YOLO
                self.car_m = YOLO("yolo26s.pt")
            if self.yolov5_dir:
                hub_args = (os.path.abspath(self.yolov5_dir), "custom")
                hub_kw = dict(path="lp_det.pt", source="local")
            else:
                hub_args = ("ultralytics/yolov5", "custom")
                hub_kw = dict(path="lp_det.pt", trust_repo=True)
            try:
                self.lp_m = torch.hub.load(*hub_args, **hub_kw)
            except Exception as e:
                if "weights_only" in str(e) or "WeightsUnpickler" in str(e):
                    import functools
                    original_load = torch.load
                    torch.load = functools.partial(original_load, weights_only=False)
                    try:
                        self.lp_m = torch.hub.load(*hub_args, **hub_kw)
                    finally:
                        torch.load = original_load
                else:
                    raise
            self.lp_m.conf = self.min_det_conf
            if gpu is None:
                gpu = torch.cuda.is_available()
            self.reader = easyocr.Reader(
                ["en"], gpu=gpu, detect_network="craft", recog_network="best_acc",
                user_network_directory=os.path.join("lp_models", "user_network"),
                model_storage_directory=os.path.join("lp_models", "models"),
            )
        finally:
            os.chdir(cwd)

    def _plates_in(self, rgb):
        out = self.lp_m(rgb).xyxy[0].cpu().numpy()
        return [(int(r[0]), int(r[1]), int(r[2]), int(r[3]), float(r[4])) for r in out]

    def _ocr(self, rgb, box):
        x1, y1, x2, y2 = box
        h, w = rgb.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 - x1 < 4 or y2 - y1 < 4:
            return "", 0.0, None
        crop_rgb = rgb[y1:y2, x1:x2]
        gray = cv2.cvtColor(cv2.resize(crop_rgb, PLATE_SIZE), cv2.COLOR_BGR2GRAY)
        try:
            # Keep the expected (box, text, confidence) return shape explicit.
            res = self.reader.recognize(gray, detail=1)
        except Exception:
            return "", 0.0, cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)
        if not res:
            return "", 0.0, cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)
        return res[0][1], float(res[0][2]), cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)

    def infer(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        regions = [(0, 0, rgb.shape[1], rgb.shape[0])]
        if self.stage == "car+plate":
            boxes = self.car_m(rgb, classes=CAR_CLASSES, verbose=False)[0].boxes.xyxy.cpu().numpy()
            if len(boxes):
                regions = [tuple(int(v) for v in b[:4]) for b in boxes]
        dets = []
        for rx1, ry1, rx2, ry2 in regions:
            sub = rgb[ry1:ry2, rx1:rx2]
            if sub.size == 0:
                continue
            for x1, y1, x2, y2, dc in self._plates_in(np.ascontiguousarray(sub)):
                box = (rx1 + x1, ry1 + y1, rx1 + x2, ry1 + y2)
                text, oc, crop = self._ocr(rgb, box)
                dets.append(Detection(box, text, oc, dc, is_valid_format(text), crop))
        dets.sort(key=lambda d: d.det_conf, reverse=True)
        return dets


def load_font(repo_dir, size=28):
    from PIL import ImageFont
    cands = [os.path.join(repo_dir, "SpoqaHanSansNeo-Light.ttf"),
             "C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for path in cands:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_text(img_bgr, text, xy, font, color=(255, 255, 255), bg=None):
    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    if bg is not None:
        l, t, r, b = draw.textbbox(xy, text, font=font)
        draw.rectangle((l - 4, t - 2, r + 4, b + 2), fill=(bg[2], bg[1], bg[0]))
    draw.text(xy, text, font=font, fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


class Voter:
    def __init__(self, window=10, min_votes=3):
        self.window, self.min_votes = window, min_votes
        self.hist = []

    def add(self, text_or_none):
        self.hist.append(text_or_none)
        self.hist = self.hist[-self.window:]

    def result(self):
        counts = Counter(t for t in self.hist if t)
        if not counts:
            return None, 0
        text, n = counts.most_common(1)[0]
        return (text if n >= self.min_votes else None), n
