"""11/18 회의 정리본 배치(docs/figures/parking_layout_2026-11-18.jpg)를 지도 JSON으로 만든다.

    python -m tools.make_layout_1118            # map/b2_layout_1118.json 생성
    python -m tools.check_map map/b2_layout_1118.json --svg map/preview_1118.svg

형식은 map/schema.md(수빈)와 같다. 좌표는 m, x 오른쪽·y 아래쪽. 보행 간선 길이는 두 점 사이 거리.
모형 실측값이 아니라 그림 비율을 옮긴 초안이다. 숫자를 고치고 다시 실행하면 된다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "map/b2_layout_1118.json"
FLOOR = "B2"

# ---- 배치 치수 (m) ----
BOARD = dict(x=0.0, y=0.0, width=29.0, depth=16.8)
C_ROW = dict(x0=3.0, slot_w=4.2, y0=0.3, y1=2.8)          # C구역 6칸 (위 벽에 붙음)
TOP_WALK = dict(y0=2.8, y1=3.6)                          # C 아래 가로 인도
ROAD_H = dict(y0=3.6, y1=6.6)                            # 가로 도로
BLOCK_Y = dict(y0=6.6, y1=15.9)                          # 세로 블록(인도 둘레 포함)
ROW_Y = [(7.2, 9.9), (9.9, 12.6), (12.6, 15.3)]          # 블록 안 칸 3줄
BLOCKS = {  # 블록 인도 둘레 x범위
    "left": (1.0, 6.6), "middle": (9.6, 19.6), "right": (22.6, 28.2)}
ROAD_V = [(6.6, 9.6), (19.6, 22.6)]                      # 세로 도로 2개
WALK_INSET = 0.3                                          # 인도 중심선 = 둘레 안쪽 0.3m
# 횡단보도는 블록 모서리에서 바로 건넌다 (정리본: 블록 위·아래 끝, 위쪽 인도 → 가운데·오른쪽 블록 왼쪽 위)

C_KIND = ["장애인", "장애인", "임산부", "임산부", "경차", "경차"]
# (구역, 블록 이름, 칸 번호들, 칸 x범위, 보행자가 서는 블록 쪽)
VERTICAL = [
    ("A", "A-1", [1, 2, 3], (1.6, 6.0), ("left", "right")),
    ("A", "A-2", [4, 5, 6], (10.2, 14.6), ("middle", "left")),
    ("B", "B-1", [1, 2, 3], (14.6, 19.0), ("middle", "right")),
    ("B", "B-2", [5, 6, 7], (23.2, 27.6), ("right", "left")),  # 그림 번호 그대로 (04 없음, 확인 필요)
]
CAMERA = {"A": "CAM-B2-01", "B": "CAM-B2-02", "C": "CAM-B2-03"}


def r(v: float) -> float:
    return round(v, 3)


def build() -> dict:
    nodes: dict[str, dict] = {}
    paths: list[list[str]] = []   # 각 path는 같은 직선 위 노드들 (정렬 후 차례로 잇는다)
    extra_edges: list[tuple[str, str]] = []

    def node(nid: str, x: float, y: float, kind: str = "junction") -> str:
        if nid in nodes:
            return nid
        nodes[nid] = {"node_id": nid, "floor": FLOOR, "x": r(x), "y": r(y), "type": kind}
        return nid

    slots = []
    # ---- C구역 ----
    top_y = (TOP_WALK["y0"] + TOP_WALK["y1"]) / 2
    top_line = []
    for i, kind in enumerate(C_KIND):
        x0 = C_ROW["x0"] + i * C_ROW["slot_w"]
        x1 = x0 + C_ROW["slot_w"]
        no = f"{i + 1:02d}"
        nid = node(f"N-C{no}", (x0 + x1) / 2, top_y, "slot_front")
        top_line.append(nid)
        slots.append({"slot_id": f"B2-C-{no}", "zone_id": "B2-C", "camera_id": CAMERA["C"],
                      "name": f"C-{no} {kind}", "node_id": nid, "roi": None,
                      "polygon": [[r(x0), C_ROW["y0"]], [r(x1), C_ROW["y0"]], [r(x1), C_ROW["y1"]], [r(x0), C_ROW["y1"]]]})
    top_line.append(node("W-TOP-L", BLOCKS["left"][0] + WALK_INSET, top_y))
    top_line.append(node("W-TOP-R", BOARD["width"] - WALK_INSET, top_y))

    # ---- 블록 둘레 인도 (사각형) ----
    ring = {}
    for name, (x0, x1) in BLOCKS.items():
        L, R = x0 + WALK_INSET, x1 - WALK_INSET
        T, B = BLOCK_Y["y0"] + WALK_INSET, BLOCK_Y["y1"] - WALK_INSET
        ring[name] = dict(L=L, R=R, T=T, B=B, left=[], right=[], top=[], bottom=[])
        for side, (x, y) in {"TL": (L, T), "TR": (R, T), "BR": (R, B), "BL": (L, B)}.items():
            nid = node(f"W-{name}-{side}", x, y)
            ring[name]["top" if side[0] == "T" else "bottom"].append(nid)
            ring[name]["left" if side[1] == "L" else "right"].append(nid)

    # ---- 세로 블록 칸 ----
    for zone, block, numbers, (sx0, sx1), (ring_name, side) in VERTICAL:
        rg = ring[ring_name]
        wx = rg["L"] if side == "left" else rg["R"]
        for no, (y0, y1) in zip(numbers, ROW_Y):
            sid = f"{no:02d}"
            nid = node(f"N-{zone}{sid}", wx, (y0 + y1) / 2, "slot_front")
            rg[side].append(nid)
            slots.append({"slot_id": f"B2-{zone}-{sid}", "zone_id": f"B2-{zone}", "camera_id": CAMERA[zone],
                          "name": f"{zone}-{sid}", "node_id": nid, "roi": None,
                          "polygon": [[sx0, y0], [sx1, y0], [sx1, y1], [sx0, y1]]})

    # ---- 위쪽 횡단보도: 위쪽 인도 → 가운데·오른쪽 블록의 왼쪽 위 모서리 ----
    top_cross_x = []
    for i, target in enumerate(("middle", "right"), 1):
        x = ring[target]["L"]
        top_cross_x.append(x)
        n_top = node(f"X-TOP{i}-N", x, top_y)
        top_line.append(n_top)
        extra_edges.append((n_top, f"W-{target}-TL"))

    # ---- 세로 도로 횡단보도: 블록 위·아래 모서리끼리 ----
    cross_y = [ring["middle"]["T"], ring["middle"]["B"]]
    for a, b in (("left", "middle"), ("middle", "right")):
        extra_edges += [(f"W-{a}-TR", f"W-{b}-TL")]
        if b == "right":   # 아래쪽 QR 입구가 이 횡단보도 가운데로 들어옴
            mid = node("X-V2S-M", (ROAD_V[1][0] + ROAD_V[1][1]) / 2, ring[b]["B"])
            extra_edges += [(f"W-{a}-BR", mid), (mid, f"W-{b}-BL")]
        else:
            extra_edges += [(f"W-{a}-BR", f"W-{b}-BL")]

    # ---- 입구 ----
    ent_l = node("ENT-L", 0.3, ring["left"]["T"], "entrance")          # 왼쪽 사람 입구
    extra_edges.append((ent_l, f"W-left-TL"))
    ent_b = node("ENT-B", (ROAD_V[1][0] + ROAD_V[1][1]) / 2, BOARD["depth"] - 0.3, "entrance")  # 아래 QR 입구
    extra_edges.append((ent_b, "X-V2S-M"))

    # ---- 직선 경로들을 차례로 이음 ----
    paths.append(sorted(top_line, key=lambda n: nodes[n]["x"]))
    for rg in ring.values():
        paths.append(sorted(rg["top"], key=lambda n: nodes[n]["x"]))
        paths.append(sorted(rg["bottom"], key=lambda n: nodes[n]["x"]))
        paths.append(sorted(rg["left"], key=lambda n: nodes[n]["y"]))
        paths.append(sorted(rg["right"], key=lambda n: nodes[n]["y"]))
    pairs = [(a, b) for p in paths for a, b in zip(p, p[1:])] + extra_edges
    edges, seen = [], set()
    for a, b in pairs:
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        na, nb = nodes[a], nodes[b]
        edges.append({"from_node": key[0], "to_node": key[1],
                      "length_m": r(math.hypot(na["x"] - nb["x"], na["y"] - nb["y"]))})

    sidewalks = [
        dict(x=1.0, y=TOP_WALK["y0"], width=BOARD["width"] - 1.0, depth=TOP_WALK["y1"] - TOP_WALK["y0"]),
        dict(x=1.0, y=0.12, width=1.0, depth=TOP_WALK["y0"] - 0.12),                     # 왼쪽 세로 인도
        *[dict(x=x0, y=BLOCK_Y["y0"], width=x1 - x0, depth=BLOCK_Y["y1"] - BLOCK_Y["y0"]) for x0, x1 in BLOCKS.values()],
    ]
    aisles = [dict(x=0.0, y=ROAD_H["y0"], width=BOARD["width"], depth=ROAD_H["y1"] - ROAD_H["y0"])]
    aisles += [dict(x=x0, y=ROAD_H["y1"], width=x1 - x0, depth=BOARD["depth"] - ROAD_H["y1"] - 0.12) for x0, x1 in ROAD_V]
    crosswalks = [dict(x=r(x - 0.5), y=ROAD_H["y0"], width=1.0, depth=ROAD_H["y1"] - ROAD_H["y0"]) for x in top_cross_x]
    crosswalks += [dict(x=x0, y=r(y - 0.5), width=x1 - x0, depth=1.0) for x0, x1 in ROAD_V for y in cross_y]

    return {
        "floor": FLOOR,
        "sample": True,
        "source": "11/18 회의 정리본 (docs/figures/parking_layout_2026-11-18.jpg), tools/make_layout_1118.py로 생성",
        "nodes": list(nodes.values()),
        "edges": edges,
        "slots": slots,
        "qr_locations": [
            {"location_id": "QR-B2-ENT1", "node_id": "ENT-L", "floor": FLOOR, "name": "왼쪽 사람 입구"},
            {"location_id": "QR-B2-ENT2", "node_id": "ENT-B", "floor": FLOOR, "name": "아래 QR 입구 (위층 연결)"},
        ],
        "zones": [{"zone_id": f"B2-{z}", "floor": FLOOR, "name": z} for z in ("A", "B", "C")],
        "cameras": [
            {"camera_id": "CAM-B2-01", "zone_id": "B2-A", "description": "CAM 01: 왼쪽 벽, A구역"},
            {"camera_id": "CAM-B2-02", "zone_id": "B2-B", "description": "CAM 02: 오른쪽 벽, B구역"},
            {"camera_id": "CAM-B2-03", "zone_id": "B2-C", "description": "CAM 03 (제안): 가운데 블록 위쪽에서 C구역을 봄"},
        ],
        "demo_layout": {
            "status": "prototype_unmeasured",
            "title": "B2 · 18면 배치 (11/18 회의)",
            "board": BOARD,
            "aisle": aisles[0],
            "aisles": aisles,
            "sidewalks": sidewalks,
            "crosswalks": crosswalks,
            "walls": [dict(x=0.0, y=0.0, width=BOARD["width"], depth=0.12, height=0.35),
                      dict(x=0.0, y=BOARD["depth"] - 0.12, width=BOARD["width"], depth=0.12, height=0.35),
                      dict(x=BOARD["width"] - 0.12, y=0.0, width=0.12, depth=BOARD["depth"], height=0.35)],
            "gates": [{"label": "출", "x": 0.3, "y": 4.3}, {"label": "입", "x": 0.3, "y": 5.9}],
            "entry_camera": {"label": "Cam1 입차", "x": 2.6, "y": 6.3, "height": 2.0},
            "camera_mounts": [
                {"camera_id": "CAM-B2-01", "label": "CAM 01 (A)", "x": 0.4, "y": 11.25, "height": 2.5},
                {"camera_id": "CAM-B2-02", "label": "CAM 02 (B)", "x": 28.6, "y": 11.25, "height": 2.5},
                {"camera_id": "CAM-B2-03", "label": "CAM 03 (C, 제안)", "x": 14.6, "y": 6.9, "height": 2.5},
            ],
        },
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(data['nodes'])} nodes, {len(data['edges'])} edges, {len(data['slots'])} slots")


if __name__ == "__main__":
    main()
