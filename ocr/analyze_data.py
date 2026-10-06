import json, re, sys, statistics
from collections import Counter, defaultdict
from pathlib import Path
from PIL import Image

root = Path(sys.argv[1] if len(sys.argv) > 1 else "../data") / "103.자동차_차종-연식-번호판_인식용_데이터"
label_root = root / "추가_데이터_보완_건_211229(폴더구조수정)"
image_root = root / "01.데이터"
SPLITS = {"train": "1.Training", "val": "2.Validation"}

PATTERNS = [
    ("3자리 (123가4567)", re.compile(r"^\d{3}[가-힣]\d{4}$")),
    ("2자리 (12가3456)", re.compile(r"^\d{2}[가-힣]\d{4}$")),
    ("지역명 (서울12가3456)", re.compile(r"^[가-힣]{2}\d{1,2}[가-힣]\d{4}$")),
]
def kind(v):
    for name, p in PATTERNS:
        if p.match(v):
            return name
    return "기타"

plates_by_split, charset = {}, Counter()
for split, folder in SPLITS.items():
    images = {p.name: p for p in (image_root / folder).rglob("*.jpg")}
    labels = sorted((label_root / folder).rglob("*.json"))
    kinds, per_plate, sizes, ratios, missing = Counter(), Counter(), [], [], 0
    others = []
    for jp in labels:
        d = json.loads(jp.read_text(encoding="utf-8"))
        v = d["value"].replace(" ", "")
        k = kind(v)
        kinds[k] += 1
        if k == "기타" and len(others) < 15:
            others.append(v)
        per_plate[v] += 1
        charset.update(v)
        ip = images.get(d["imagePath"])
        if ip is None:
            missing += 1
            continue
        w, h = Image.open(ip).size
        sizes.append((w, h))
        ratios.append(w / h)
    plates_by_split[split] = set(per_plate)
    n = len(labels)
    print(f"\n===== {split} =====")
    print(f"라벨 {n}장 / 이미지 {len(images)}장 / 이미지 없는 라벨 {missing}개")
    for k, c in kinds.most_common():
        print(f"  {k:<22} {c:>7}장 ({c / n * 100:5.1f}%)")
    if others:
        print("  기타 예시:", others)
    cnt = list(per_plate.values())
    print(f"고유 번호판 {len(per_plate)}개 / 번호판당 평균 {statistics.mean(cnt):.2f}장, 최대 {max(cnt)}장")
    if sizes:
        ws, hs = sorted(s[0] for s in sizes), sorted(s[1] for s in sizes)
        q = lambda a, r: a[int(len(a) * r)]
        print(f"가로 px  min {ws[0]} / 중앙 {q(ws, .5)} / 90% {q(ws, .9)} / max {ws[-1]}")
        print(f"세로 px  min {hs[0]} / 중앙 {q(hs, .5)} / 90% {q(hs, .9)} / max {hs[-1]}")
        two_line = sum(r < 2.5 for r in ratios)
        print(f"가로/세로 비율 < 2.5 (두 줄 번호판 추정): {two_line}장 ({two_line / len(ratios) * 100:.1f}%)")

overlap = plates_by_split["train"] & plates_by_split["val"]
print(f"\n학습/검증에 동시에 있는 번호판: {len(overlap)}개")
chars = sorted(charset)
hangul = [c for c in chars if "가" <= c <= "힣"]
print(f"문자 종류 {len(chars)}개 (한글 {len(hangul)}개): {''.join(hangul)}")
print("숫자/기타:", "".join(c for c in chars if c not in hangul))
Path("charset.txt").write_text("".join(chars), encoding="utf-8")
print("→ charset.txt 저장 완료")
