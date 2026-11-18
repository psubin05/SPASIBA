"""번호판 정규화·형식 검사·편집 거리 (인터페이스 1.1, v0.4).

지역명·용도 문자 목록은 Pi 기존 OCR 코드(raspberrypi 브랜치 src/postprocessing.py)와 같다.
"""
from __future__ import annotations

import re
import unicodedata

REGIONS: tuple[str, ...] = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
USE_CHARS = "가거고구나너노누다더도두라러로루마머모무바배버보부사서소수아어오우자저조주지하허호"

PLATE_RE = re.compile(rf"(?:{'|'.join(REGIONS)})?[0-9]{{2,3}}[{USE_CHARS}][0-9]{{4}}")
_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


def normalize(text: str | None) -> str:
    """공백·하이픈·가운뎃점 제거, 전각 숫자 → 반각 (그 밖의 글자는 남겨 형식 검사에서 걸러짐)."""
    text = unicodedata.normalize("NFC", text or "").translate(_FULLWIDTH)
    return re.sub(r"[\s\-·]", "", text)


def is_valid(plate_norm: str) -> bool:
    return isinstance(plate_norm, str) and PLATE_RE.fullmatch(plate_norm) is not None


def _tokens(plate: str) -> list[str]:
    """지역명은 한 덩어리(1글자), 나머지는 글자 단위."""
    for region in REGIONS:
        if plate.startswith(region):
            return [region, *plate[len(region):]]
    return list(plate)


def edit_distance(a: str, b: str) -> int:
    x, y = _tokens(a), _tokens(b)
    prev = list(range(len(y) + 1))
    for i, tx in enumerate(x, 1):
        cur = [i]
        for j, ty in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (tx != ty)))
        prev = cur
    return prev[-1]
