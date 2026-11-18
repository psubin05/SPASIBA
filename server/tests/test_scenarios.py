import copy

import pytest

from tools.scenario import ScenarioError, all_scenarios, load_scenario, validate_scenario

BASE = {
    "name": "t",
    "cameras": [{"camera_id": "CAM-B2-01"}],
    "steps": [
        {"type": "event", "camera_id": "CAM-B2-01", "slot_id": "B2-A-03",
         "plate_number": "12가3456", "event_ref": "e1"},
    ],
}


def _with_step(step):
    sc = copy.deepcopy(BASE)
    sc["steps"].append(step)
    return sc


def test_all_scenarios_load():
    paths = all_scenarios()
    assert len(paths) == 9
    for p in paths:
        sc = load_scenario(p)
        assert sc["name"] and sc["description"]


def test_base_is_valid():
    validate_scenario(copy.deepcopy(BASE))


def test_repeat_of_known_ref_ok():
    validate_scenario(_with_step({"type": "event", "repeat_of": "e1"}))


def test_repeat_of_unknown_ref_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(_with_step({"type": "event", "repeat_of": "nope"}))


def test_unknown_camera_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(_with_step({"type": "event", "camera_id": "CAM-X", "slot_id": "B2-A-01",
                                      "plate_number": "12가3456"}))


def test_bad_plate_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(_with_step({"type": "event", "camera_id": "CAM-B2-01",
                                      "slot_id": "B2-A-01", "plate_number": "12가345"}))


def test_bad_plate_allowed_when_expected_invalid():
    validate_scenario(_with_step({"type": "event", "camera_id": "CAM-B2-01",
                                  "slot_id": "B2-A-01", "plate_number": "12가345",
                                  "expect_invalid": True}))


def test_bad_slot_format_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(_with_step({"type": "event", "camera_id": "CAM-B2-01",
                                      "slot_id": "B2A1", "plate_number": "12가3456"}))


def test_slot_of_other_zone_allowed():
    """v0.4: 카메라 한 대가 여러 구역의 칸을 볼 수 있다."""
    validate_scenario(_with_step({"type": "event", "camera_id": "CAM-B2-01",
                                  "slot_id": "B2-B-01", "plate_number": "12가3456"}))


def test_unknown_step_type_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(_with_step({"type": "explode"}))


def test_missing_required_key_rejected():
    sc = copy.deepcopy(BASE)
    del sc["cameras"]
    with pytest.raises(ScenarioError):
        validate_scenario(sc)


def test_duplicate_event_ref_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(_with_step({"type": "event", "camera_id": "CAM-B2-01",
                                      "slot_id": "B2-A-01", "plate_number": "12가3456",
                                      "event_ref": "e1"}))


def test_bad_json_file_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioError):
        load_scenario(p)


def test_step_after_disconnect_rejected():
    sc = _with_step({"type": "disconnect", "camera_id": "CAM-B2-01", "abrupt": True})
    sc["steps"].append({"type": "event", "camera_id": "CAM-B2-01", "slot_id": "B2-A-01",
                        "plate_number": "12가3456"})
    with pytest.raises(ScenarioError):
        validate_scenario(sc)
