"""아직 구현하지 않은 API 자리: 수꽝 관리자 확인(작업 9, 나중에), 떵개·수빈 지도 API(수빈 앱과 합칠 때).

경로·응답 형식은 docs/server_interface.md 3장 기준.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query


def _todo(owner: str, task: str):
    raise HTTPException(status_code=501, detail={"error": {"code": "NOT_IMPLEMENTED", "message": f"{owner} 작업 {task}에서 구현 예정"}})


# 수꽝 API: 입·출차·조회는 app/routers/parking.py. 관리자 확인(작업 9)은 나중에 구현.
# 처리 함수(app/parking.py: list_reviews, resolve_review, review_crop_path, list_auto_assignments)는 준비돼 있다.
admin = APIRouter(tags=["수꽝: 입·출차 · 조회 · 관리자"])


@admin.get("/admin/reviews")
def list_reviews():
    _todo("수꽝", "9")


@admin.get("/admin/reviews/{review_id}/crop")
def review_crop(review_id: str):
    _todo("수꽝", "9")


@admin.post("/admin/reviews/{review_id}/resolve")
def resolve_review(review_id: str):
    _todo("수꽝", "9")


# ---- 떵개: 지도·경로 ----
dg = APIRouter(tags=["떵개: QR · 경로 · 지도"])


@dg.get("/qr/{location_id}")
def resolve_qr(location_id: str):
    _todo("떵개", "A")


@dg.get("/route")
def route(from_: str | None = Query(None, alias="from"), to: str | None = None):
    _todo("떵개", "A")


@dg.get("/map")
def map_data(floor: str | None = None):
    _todo("떵개", "A")
