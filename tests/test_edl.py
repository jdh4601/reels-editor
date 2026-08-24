import pytest

from reels_editor import edl


def test_validate_ok(edl_doc: dict, segments: dict) -> None:
    assert edl.validate_edl(edl_doc, segments) == []


def test_validate_unknown_seg_id(edl_doc: dict, segments: dict) -> None:
    edl_doc["cuts"][0]["seg_ids"] = ["없는id"]
    errs = edl.validate_edl(edl_doc, segments)
    assert any("없는id" in e for e in errs)


def test_validate_verbatim_mismatch(edl_doc: dict, segments: dict) -> None:
    edl_doc["cuts"][0]["text"] = "지어낸 문장"
    errs = edl.validate_edl(edl_doc, segments)
    assert any("verbatim" in e for e in errs)


def test_validate_empty_cuts(segments: dict) -> None:
    errs = edl.validate_edl({"cuts": []}, segments)
    assert any("cuts" in e for e in errs)


def test_ordered_segments_flattens_in_edl_order(edl_doc: dict, segments: dict) -> None:
    out = edl.ordered_segments(edl_doc, segments)
    assert [o["text"] for o in out] == [
        "그런데 도저히 꿈을 포기 못 하겠더라고요", "그래서 바로 시작했습니다"]


def test_ordered_segments_uses_korean_subtitle_translations(edl_doc: dict, segments: dict) -> None:
    edl_doc["subtitle_translations"] = {
        "t1": "하지만 꿈을 포기할 수 없었어요.",
        "t2": "그래서 바로 시작했죠.",
    }

    out = edl.ordered_segments(edl_doc, segments)

    assert [item["text"] for item in out] == [
        "하지만 꿈을 포기할 수 없었어요.",
        "그래서 바로 시작했죠.",
    ]


def test_estimate_duration_applies_speed(edl_doc: dict, segments: dict) -> None:
    # t1: 10s + t2: 8s = 18s 소스 → 1.2배속이면 15.0s
    assert edl.estimate_duration_s(edl_doc, segments, speed=1.2) == pytest.approx(15.0, abs=0.1)
