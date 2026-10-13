"""Roboflow Universe 번호판 데이터셋 다운로드

  python download_rf.py list                         # 데이터셋별 버전 목록 (장수, 증강, 분할)
  python download_rf.py get lp_detect=3 alpr=1 ...   # 고른 버전을 YOLOv11 형식으로 받기

API 키는 실행할 때 입력받는다 (화면·명령 기록·파일에 남지 않음).
받을 폴더가 이미 있으면 건너뛴다 (덮어쓰지 않음).
"""
import sys
from getpass import getpass
from pathlib import Path
from roboflow import Roboflow

DATA = Path(__file__).resolve().parents[2] / "data"
DATASETS = {                                      # 짧은 이름: (workspace, project, 저장 폴더)
    "lp_detect":      ("novitec-nh1uq",      "lp-detect-k3yuj",               "rf_lp_detect"),
    "plate_night":    ("insiks-workspace",   "korean-license-plate-detector", "rf_plate_night"),
    "alpr":           ("test-mkn0z",         "alpr-uyrnd",                    "rf_alpr"),
    "car_with_plate": ("test-r1f11",         "car_with_plate-ykdgx",          "rf_car_with_plate"),
    "korean_license": ("new-workspace-wbfgv", "korean-license",               "rf_korean_license"),
}

if len(sys.argv) < 2 or sys.argv[1] not in ("list", "get"):
    sys.exit(__doc__)
rf = Roboflow(api_key=getpass("Roboflow API 키 (입력해도 화면에 안 보임): ").strip())

if sys.argv[1] == "list":
    for name, (ws, proj, _) in DATASETS.items():
        print(f"\n=== {name}  ({ws}/{proj})")
        try:
            project = rf.workspace(ws).project(proj)
            print(f"    클래스: {project.classes}")
            for v in project.versions():
                aug = v.augmentation or {}
                print(f"    v{v.version:<3} {v.images:>6}장  분할 {v.splits}  "
                      f"증강 {'없음' if not aug else list(aug)}  이름 '{v.name}'")
        except Exception as e:
            print(f"    실패: {e}")
    print("\n증강 없는 버전을 골라 다음처럼 받는다: python download_rf.py get lp_detect=1 alpr=2 ...")
else:
    for arg in sys.argv[2:]:
        name, ver = arg.split("=")
        ws, proj, folder = DATASETS[name]
        out = DATA / folder
        if out.exists():
            print(f"[건너뜀] {out} 이미 있음")
            continue
        print(f"[받는 중] {name} v{ver} → {out}")
        rf.workspace(ws).project(proj).version(int(ver)).download("yolov11", location=str(out))
    print("완료")
