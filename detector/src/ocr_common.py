"""Shared Korean plate tokenization and CTC helpers."""

from __future__ import annotations

import re

REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
           "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주")
REGION_TO_TOKEN = {region: chr(0xE000 + i) for i, region in enumerate(REGIONS)}
TOKEN_TO_REGION = {token: region for region, token in REGION_TO_TOKEN.items()}
STANDARD_RE = re.compile(r"^(\d{2,3})([가-힣])(\d{4})$")
REGION_RE = re.compile(r"^(" + "|".join(REGIONS) + r")(\d{2,3})([가-힣])(\d{4})$")


def normalize_plate(text: str) -> str:
    return re.sub(r"[\s-]", "", text or "")


def is_supported(text: str) -> bool:
    text = normalize_plate(text)
    return bool(STANDARD_RE.fullmatch(text) or REGION_RE.fullmatch(text))


def encode_regions(text: str) -> str:
    text = normalize_plate(text)
    for region, token in REGION_TO_TOKEN.items():
        if text.startswith(region):
            return token + text[len(region):]
    return text


def decode_regions(text: str) -> str:
    return "".join(TOKEN_TO_REGION.get(char, char) for char in text)


def split_two_line(text: str) -> tuple[str, str]:
    text = normalize_plate(text)
    region_match = REGION_RE.fullmatch(text)
    if region_match:
        region, prefix, usage, serial = region_match.groups()
        return encode_regions(region + prefix), usage + serial
    standard_match = STANDARD_RE.fullmatch(text)
    if standard_match:
        prefix, usage, serial = standard_match.groups()
        return prefix + usage, serial
    raise ValueError(f"Unsupported Korean plate: {text}")

