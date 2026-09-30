#!/usr/bin/env python3
"""Batch test a folder of plate images and write CSV, Markdown, and annotations."""
import argparse
import csv
import difflib
import os
import sys
import time
from collections import Counter, defaultdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lp_engine import KoreanLP, normalize, load_font, draw_text  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def imread_unicode(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_unicode(path, img):
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".jpg", img)
    if ok:
        buf.tofile(path)


def parse_name(fname):
    toks = os.path.splitext(fname)[0].split("_")
    return toks[0], [t for t in toks[1:] if t and not t.isdigit()]


def load_labels(csv_path):
    out = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            conds = [c for c in (row.get("conditions") or "").split(";") if c]
            out[row["filename"]] = (normalize(row["plate"]), conds)
    return out


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_acc(truth, pred):
    if not truth:
        return 0.0
    return max(0.0, 1.0 - levenshtein(truth, pred) / len(truth))


def pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "-"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, help="시험 이미지 폴더")
    ap.add_argument("--repo", default=".", help="EasyKoreanLpDetector 폴더")
    ap.add_argument("--stage", default="plate", choices=["plate", "car+plate"])
    ap.add_argument("--labels", default=None, help="정답 CSV (filename,plate,conditions)")
    ap.add_argument("--out", default="results")
    ap.add_argument("--yolov5", default=None)
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args()

    if not os.path.isdir(args.images):
        sys.exit(f"이미지 폴더가 없습니다: {args.images}")
    files = sorted(f for f in os.listdir(args.images) if os.path.splitext(f)[1].lower() in IMG_EXT)
    if not files:
        sys.exit(f"이미지가 없습니다: {args.images}")
    labels = load_labels(args.labels) if args.labels else {}
    os.makedirs(os.path.join(args.out, "annotated"), exist_ok=True)
    print("모델 로드 중...")
    eng = KoreanLP(args.repo, stage=args.stage, min_det_conf=args.conf, yolov5_dir=args.yolov5)
    font = load_font(os.path.abspath(args.repo), 30)
    print(f"이미지 {len(files)}장 시험 시작\n")

    rows = []
    for k, fn in enumerate(files, 1):
        img = imread_unicode(os.path.join(args.images, fn))
        if img is None:
            print(f"  [건너뜀] 읽을 수 없음: {fn}")
            continue
        truth, conds = labels.get(fn) or parse_name(fn)
        truth = normalize(truth)
        t0 = time.time()
        dets = eng.infer(img)
        ms = (time.time() - t0) * 1000
        top = dets[0] if dets else None
        pred = normalize(top.text) if top else ""
        detected = top is not None
        exact = detected and pred == truth
        rows.append(dict(
            filename=fn, truth=truth, pred=pred, detected=int(detected), exact=int(exact),
            char_acc=round(char_acc(truth, pred), 3) if detected else 0.0,
            format_ok=int(bool(top and top.valid)), n_dets=len(dets),
            det_conf=round(top.det_conf, 3) if top else "", ocr_conf=round(top.ocr_conf, 3) if top else "",
            ms=round(ms, 1), conditions=";".join(conds)))
        vis = img.copy()
        for det in dets:
            x1, y1, x2, y2 = det.box
            col = (0, 200, 0) if det.text and normalize(det.text) == truth else (0, 0, 255)
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, max(2, vis.shape[1] // 400))
            vis = draw_text(vis, det.text, (x1, max(0, y1 - 40)), font, (255, 255, 255), col)
        vis = draw_text(vis, f"정답 {truth} / {'일치' if exact else ('불일치' if detected else '미검출')}",
                        (10, 10), font, (255, 255, 255), (0, 140, 0) if exact else (0, 0, 200))
        imwrite_unicode(os.path.join(args.out, "annotated", os.path.splitext(fn)[0] + ".jpg"), vis)
        mark = "O" if exact else ("X" if detected else "-")
        print(f"  [{k:>3}/{len(files)}] {mark} {fn:<40} 정답={truth:<10} 인식={pred or '(미검출)':<12} {ms:6.0f}ms")

    if not rows:
        sys.exit("처리된 이미지가 없습니다.")
    csv_path = os.path.join(args.out, "results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    n = len(rows)
    n_det = sum(r["detected"] for r in rows)
    n_ex = sum(r["exact"] for r in rows)
    n_fmt = sum(r["format_ok"] for r in rows)
    mean_ca = np.mean([r["char_acc"] for r in rows])
    mean_ms = np.mean([r["ms"] for r in rows])
    by_cond = defaultdict(list)
    for row in rows:
        for cond in (row["conditions"].split(";") if row["conditions"] else ["(조건 없음)"]):
            by_cond[cond].append(row)
    wrong = [r for r in rows if r["detected"] and not r["exact"]]
    missed = [r for r in rows if not r["detected"]]
    confusions = Counter()
    for row in wrong:
        sm = difflib.SequenceMatcher(None, row["truth"], row["pred"])
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace":
                confusions[(row["truth"][i1:i2], row["pred"][j1:j2])] += 1
            elif tag == "delete":
                confusions[(row["truth"][i1:i2], "(누락)")] += 1
            elif tag == "insert":
                confusions[("(없음)", row["pred"][j1:j2])] += 1

    lines = ["# 번호판 인식 시험 요약\n",
             f"- 시험 폴더: `{args.images}` / 모드: `{args.stage}` / 이미지 {n}장\n",
             "| 지표 | 값 |\n|---|---|",
             f"| 번호판 검출률 | {pct(n_det, n)} ({n_det}/{n}) |",
             f"| **전체 문자 일치율 (NFR-01 기준)** | **{pct(n_ex, n)}** ({n_ex}/{n}) |",
             f"| 번호판 형식(정규식) 통과율 | {pct(n_fmt, n)} |",
             f"| 평균 글자 정확도 | {100 * mean_ca:.1f}% |",
             f"| 이미지당 평균 처리 시간 | {mean_ms:.0f} ms (현재 컴퓨터 기준) |\n"]
    ref = "목표(90%) 이상" if n_ex / n >= 0.9 else "목표(90%) 미만"
    lines.append(f"> 참고: NFR-01은 지정 조건에서 100회 시험 시 90% 이상입니다. 이번 결과는 {n}장 기준 {ref}이며, 최종 판정은 실제 카메라·번호표·지정 조건에서 100회 시험으로 해야 합니다.\n")
    lines.extend(["## 조건별 결과\n", "| 조건 | 장수 | 검출률 | 전체 일치율 |\n|---|---|---|---|"])
    for cond in sorted(by_cond):
        rs = by_cond[cond]
        lines.append(f"| {cond} | {len(rs)} | {pct(sum(r['detected'] for r in rs), len(rs))} | {pct(sum(r['exact'] for r in rs), len(rs))} |")
    lines.extend(["", "## 틀린 사례 (검출됐지만 문자열 불일치)\n"])
    if wrong:
        lines.extend(["| 파일 | 정답 | 인식 | 글자정확도 | 조건 |\n|---|---|---|---|---|"] +
                      [f"| {r['filename']} | {r['truth']} | {r['pred']} | {r['char_acc']:.2f} | {r['conditions']} |" for r in wrong])
    else:
        lines.append("없음")
    lines.extend(["", "## 미검출 (번호판을 못 찾음)\n"])
    lines.append("\n".join(f"- {r['filename']} ({r['conditions']})" for r in missed) if missed else "없음")
    if confusions:
        lines.extend(["", "## 자주 틀리는 글자\n", "| 정답 | 인식 | 횟수 |\n|---|---|---|"])
        lines.extend(f"| {a} | {b} | {count} |" for (a, b), count in confusions.most_common(15))
    lines.extend(["", "## 오류 유형별 다음 조치\n",
                  "- 미검출이 많음 → 번호표 크기·대비·조명·거리 조정, 탐지 신뢰도 `--conf` 낮춰 재시험",
                  "- 검출은 되는데 글자가 틀림 → 위 '자주 틀리는 글자' 확인, 번호표 서체·한글 글자를 모델 지원 글자로 교체",
                  "- 특정 각도(yaw/pitch)에서만 실패 → 모서리 기반 정면화 단계 추가 검토"])
    md_path = os.path.join(args.out, "summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n" + "=" * 60)
    print(f"검출률 {pct(n_det, n)} | 전체 문자 일치율 {pct(n_ex, n)} | 글자 정확도 {100 * mean_ca:.1f}% | 평균 {mean_ms:.0f}ms")
    print(f"결과 저장: {csv_path}\n         {md_path}\n         {os.path.join(args.out, 'annotated')}/")


if __name__ == "__main__":
    main()
