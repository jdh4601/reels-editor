import pytest


def _video_seg(sid: str, tl_start: int, tl_dur: int, src_start: int, speed: float = 1.0) -> dict:
    return {
        "id": sid,
        "material_id": "VID",
        "speed": speed,
        "target_timerange": {"start": tl_start, "duration": tl_dur},
        "source_timerange": {"start": src_start, "duration": int(tl_dur * speed)},
    }


def _text_mat(mid: str, text: str) -> dict:
    return {"id": mid, "recognize_text": text, "content": "", "add_type": 1}


def _text_seg(sid: str, mid: str, tl_start: int, tl_dur: int) -> dict:
    return {"id": sid, "material_id": mid,
            "target_timerange": {"start": tl_start, "duration": tl_dur}}


@pytest.fixture
def raw_draft() -> dict:
    """단일 비디오 세그먼트(speed 1.0) + 자막 3개."""
    return {
        "fps": 30,
        "tracks": [
            {"type": "video", "segments": [_video_seg("v0", 0, 30_000_000, 0)]},
            {"type": "text", "segments": [
                _text_seg("t0", "m0", 0, 5_000_000),
                _text_seg("t1", "m1", 5_000_000, 10_000_000),
                _text_seg("t2", "m2", 15_000_000, 8_000_000),
            ]},
        ],
        "materials": {
            "videos": [{"id": "VID", "path": "/tmp/footage.mp4", "duration": 30_000_000}],
            "texts": [
                _text_mat("m0", "저는 원래 대기업에 합격했어요"),
                _text_mat("m1", "그런데 도저히 꿈을 포기 못 하겠더라고요"),
                _text_mat("m2", "그래서 바로 시작했습니다"),
            ],
        },
    }


@pytest.fixture
def segments(raw_draft: dict) -> dict:
    from reels_editor import capcut
    return capcut.build_segments(raw_draft)


@pytest.fixture
def edl_doc() -> dict:
    """raw_draft와 짝을 이루는 승인된 EDL."""
    return {
        "story": {"five_lines": {"situation": "s", "desire": "d", "conflict": "c",
                                 "change": "ch", "result": "r"}, "lens": "lens"},
        "title_candidates": [{"text": "대기업을 버린 이유", "keyword": "대기업"}],
        "selected_title": 0,
        "subtitle_keywords": ["대기업"],
        "cuts": [
            {"beat": "훅", "seg_ids": ["t1"], "broll_marker": None},
            {"beat": "라스트 답", "seg_ids": ["t2"], "broll_marker": None},
        ],
    }
