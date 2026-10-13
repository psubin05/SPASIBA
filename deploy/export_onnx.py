"""Pi 배포용 ONNX 변환 (서버에서 실행)

  python export_onnx.py          # → deploy/models/

  plate_{640,416,320}.onnx   ① 번호판 검출 (plate_v3, 입력 크기별)
  line_det.onnx              ② 줄 검출 (PP-OCRv5 mobile det)
  ocr_v1.onnx                ③ 글자 인식 + ocr_v1.json (글자 목록, 입력 크기)
"""
import json, shutil, subprocess, sys
from pathlib import Path
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "models"; OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "ocr"))

# ① 검출: Ultralytics 내보내기 (가중치 옆에 .onnx가 생기므로 옮김)
from ultralytics import YOLO
for size in (640, 416, 320):
    f = YOLO(str(ROOT / "detector/weights/plate_v3.pt")).export(format="onnx", imgsz=size, simplify=True, opset=17)
    shutil.move(f, OUT / f"plate_{size}.onnx")
    print(f"① plate_{size}.onnx")

# ② 줄 검출: paddle2onnx
det_dir = Path.home() / ".paddlex/official_models/PP-OCRv5_mobile_det"
subprocess.run(["paddle2onnx", "--model_dir", str(det_dir), "--model_filename", "inference.json",
                "--params_filename", "inference.pdiparams", "--save_file", str(OUT / "line_det.onnx"),
                "--opset_version", "14"], check=True, capture_output=True)
print("② line_det.onnx")

# ③ 인식: torch.onnx (GRU 포함이라 기존 TorchScript 방식 사용)
from train_ocr import PlateOCR
ck = torch.load(ROOT / "ocr/weights/ocr_v1.pt", map_location="cpu")
model = PlateOCR(len(ck["tokens"]) + 1).eval()
model.load_state_dict(ck["model"])
torch.onnx.export(model, torch.zeros(1, 3, ck["h"], ck["w"]), OUT / "ocr_v1.onnx", input_names=["image"],
                  output_names=["log_probs"], dynamic_axes={"image": {0: "batch"}, "log_probs": {0: "batch"}},
                  opset_version=17, dynamo=False)
(OUT / "ocr_v1.json").write_text(json.dumps({"tokens": [t.strip("<>") for t in ck["tokens"]], "h": ck["h"], "w": ck["w"]},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
print("③ ocr_v1.onnx, ocr_v1.json")
for f in sorted(OUT.iterdir()):
    print(f"  {f.name:<20} {f.stat().st_size / 1e6:6.2f} MB")
