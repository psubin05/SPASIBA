"""번호 규칙(인터페이스 1.1)과 매칭 판단(4장) — DB 없는 순수 함수."""
import uuid

import pytest

from app.matching import Candidate, decide
from app.plates import edit_distance, is_valid, normalize


# ---- 번호 규칙 ----
@pytest.mark.parametrize("raw,norm", [
    ("12가 3456", "12가3456"), ("12-가-3456", "12가3456"), ("서울·12가3456", "서울12가3456"),
    ("１２가３４５６", "12가3456"), (" 123가4567\n", "123가4567"),
])
def test_normalize(raw, norm):
    assert normalize(raw) == norm


@pytest.mark.parametrize("plate", ["12가3456", "123가4567", "서울12가3456", "경기71아3535", "12허3456"])
def test_valid_plates(plate):
    assert is_valid(plate)


@pytest.mark.parametrize("plate", [
    "12가345", "1가3456", "1234가3456", "12각3456",  # 각: 용도 문자 목록에 없음
    "12A3456", "뉴욕12가3456", "", "12가3456\n", "١٢가3456",  # 아라비아 숫자
])
def test_invalid_plates(plate):
    assert not is_valid(plate)


@pytest.mark.parametrize("a,b,d", [
    ("12가3456", "12가3456", 0), ("12가3456", "12가3458", 1), ("12가3456", "12나3456", 1),
    ("12가3456", "123가3456", 1),          # 한 글자 추가
    ("서울12가3456", "12가3456", 1),        # 지역명은 1글자
    ("서울12가3456", "부산12가3456", 1),    # 지역명 바뀜 = 1
    ("12가3456", "34나5678", 6),
])
def test_edit_distance(a, b, d):
    assert edit_distance(a, b) == d == edit_distance(b, a)


# ---- 매칭 판단 ----
def _c(plate):
    return Candidate(session_id=uuid.uuid4(), plate_norm=plate)


def test_exact_match_confirms():
    a, b = _c("12가3456"), _c("12가3457")
    d = decide("12가3456", votes=None, candidates=[a, b])
    assert (d.method, d.session_id) == ("EXACT", a.session_id)


def test_edit1_single_candidate_high_votes_confirms():
    a = _c("12가3456")
    d = decide("12가3458", votes=5, candidates=[a, _c("34나5678")])
    assert (d.method, d.session_id) == ("EDIT1", a.session_id)


def test_edit1_low_votes_pends():
    assert decide("12가3458", votes=4, candidates=[_c("12가3456")]).method is None


def test_edit1_without_votes_pends():
    assert decide("12가3458", votes=None, candidates=[_c("12가3456")]).method is None


def test_edit1_two_candidates_pends():
    d = decide("12가3458", votes=9, candidates=[_c("12가3456"), _c("12가3457")])
    assert d.method is None
    assert sorted(c["distance"] for c in d.nearby) == [1, 1]


def test_no_candidates_pends():
    d = decide("12가3456", votes=9, candidates=[])
    assert d.method is None and d.nearby == []


def test_min_votes_configurable():
    a = _c("12가3456")
    assert decide("12가3458", votes=3, candidates=[a], min_votes=3).method == "EDIT1"


def test_nearby_lists_close_candidates_sorted():
    far, near = _c("99하9999"), _c("12가3456")
    d = decide("12가3458", votes=1, candidates=[far, near, _c("12가3466")])
    assert [c["plate_norm"] for c in d.nearby] == ["12가3456", "12가3466"]
    assert d.nearby[0]["session_id"] == str(near.session_id)
