from __future__ import annotations

import re
import unicodedata


REGIONS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
USE_CHARS = "가거고구나너노누다더도두라러로루마머모무바배버보부사서소수아어오우자저조주지하허호"
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
PLATE_PATTERN = re.compile(
    rf"(?:(?:{'|'.join(REGIONS)}))?\d{{2,3}}[{re.escape(USE_CHARS)}]\d{{4}}"
)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "").translate(FULLWIDTH_DIGITS)
    return re.sub(r"[^0-9가-힣]", "", text)


def extract_plate(value: str) -> tuple[str, bool]:
    cleaned = normalize(value)
    matches = list(PLATE_PATTERN.finditer(cleaned))
    if not matches:
        return cleaned, False
    matches.sort(key=lambda match: (-bool(match.group().startswith(REGIONS)), -len(match.group()), match.start()))
    return matches[0].group(), True
