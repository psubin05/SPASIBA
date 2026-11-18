"""매칭 판단 (인터페이스 4장 규칙 ①~③). DB 없는 순수 함수.

① plate_norm이 후보 하나와 정확히 일치 → EXACT
② 정확히 일치는 없고, 편집 거리 1인 후보가 딱 한 대 + votes ≥ min_votes → EDIT1
③ 그 외 → 보류 (method None). ④ 120초 초과 처리는 app/parking.py
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .plates import edit_distance

NEARBY_MAX_DISTANCE = 2  # 관리자 화면에 보여 줄 후보 범위
NEARBY_LIMIT = 5


@dataclass(frozen=True)
class Candidate:
    session_id: uuid.UUID
    plate_norm: str
    plate_number: str | None = None
    entered_at: str | None = None  # ISO 문자열 (관리자 화면용)


@dataclass
class Decision:
    method: str | None                 # "EXACT" | "EDIT1" | None(보류)
    session_id: uuid.UUID | None = None
    nearby: list[dict] = field(default_factory=list)  # 보류 시 관리자 화면 후보


def decide(plate_norm: str, votes: int | None, candidates: list[Candidate], min_votes: int = 5) -> Decision:
    scored = [(edit_distance(plate_norm, c.plate_norm), c) for c in candidates]
    exact = [c for d, c in scored if d == 0]
    if len(exact) == 1:
        return Decision("EXACT", exact[0].session_id)
    one = [c for d, c in scored if d == 1]
    if not exact and len(one) == 1 and votes is not None and votes >= min_votes:
        return Decision("EDIT1", one[0].session_id)
    near = sorted(((d, c) for d, c in scored if d <= NEARBY_MAX_DISTANCE),
                  key=lambda t: (t[0], t[1].plate_norm))[:NEARBY_LIMIT]
    return Decision(None, nearby=[
        {"session_id": str(c.session_id), "plate_number": c.plate_number or c.plate_norm,
         "plate_norm": c.plate_norm, "entered_at": c.entered_at, "distance": d}
        for d, c in near])
