"""ONNX 버전(pi_reader)이 서버 버전(ocr/plate_reader)과 같은 결과를 내는지 확인 (서버에서 실행)

  python check_onnx.py [--n 500] [--size 640]

AI Hub OCR crop 중 test split 번호(학습에 쓰지 않은 번호)의 원본 사진에 두 버전을 돌려
번호판 전체 일치율, 두 버전의 결과 일치율, 줄 수 일치율을 비교한다.
"""
import argparse, json, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ocr"))
import make_ocr_v1 as prep                                         # noqa: E402
from pi_reader import PiPlateReader                                # noqa: E402
from plate_reader import PlateReader                               # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=500)
ap.add_argument("--size", type=int, default=640)
a = ap.parse_args()

random.seed(0)
images = {p.name: p for p in prep.IMAGES.rglob("*.jpg")}
pairs, seen = [], set()
for jp in sorted(prep.LABELS.rglob("*.json")):
    d = json.loads(jp.read_text(encoding="utf-8"))
    v = d["value"].replace(" ", "")
    if v in seen or not (prep.STD.match(v) or prep.REGION.match(v)) or prep.split_of(v) != "test" or d["imagePath"] not in images:
        continue
    seen.add(v)
    pairs.append((images[d["imagePath"]], v))
pairs = random.sample(pairs, min(a.n, len(pairs)))

torch_r, onnx_r = PlateReader(), PiPlateReader(a.size)
st = {"torch 일치": 0, "onnx 일치": 0, "두 버전 같은 결과": 0, "줄 수 같음": 0}
for path, v in pairs:
    img = prep.imread(path)
    top = lambda res: max(res, key=lambda p: p["det_conf"]) if res else {"text": "", "n_lines": -1}
    t, o = top(torch_r(img)), top(onnx_r(img))
    st["torch 일치"] += t["text"] == v
    st["onnx 일치"] += o["text"] == v
    st["두 버전 같은 결과"] += t["text"] == o["text"]
    st["줄 수 같음"] += t["n_lines"] == o["n_lines"]
print(f"AI Hub test 번호 원본 {len(pairs)}장 (onnx 입력 {a.size})")
for k, c in st.items():
    print(f"  {k:<12} {c / len(pairs):.3f}")
