from pathlib import Path

import pytest

from reels_editor.style import load_style

@pytest.fixture
def segments() -> dict:
    return {
        "video_path": "/tmp/footage.mp4",
        "segments": [
            {
                "id": "t0",
                "text": "저는 원래 대기업에 합격했어요",
                "source_start_us": 0,
                "source_end_us": 5_000_000,
            },
            {
                "id": "t1",
                "text": "그런데 도저히 꿈을 포기 못 하겠더라고요",
                "source_start_us": 5_000_000,
                "source_end_us": 15_000_000,
            },
            {
                "id": "t2",
                "text": "그래서 바로 시작했습니다",
                "source_start_us": 15_000_000,
                "source_end_us": 23_000_000,
            },
        ],
    }


@pytest.fixture
def edl_doc() -> dict:
    """segments 픽스처와 짝을 이루는 승인된 EDL."""
    return {
        "story": {"five_lines": {"situation": "s", "desire": "d", "conflict": "c",
                                 "change": "ch", "result": "r"}, "lens": "lens"},
        "title_candidates": [
            {"text": "대기업을 버린 이유", "keyword": "대기업"},
            {"text": "꿈을 포기 못 한 순간", "keyword": "꿈"},
            {"text": "바로 시작한 대표의 선택", "keyword": "선택"},
        ],
        "selected_title": 0,
        "subtitle_keywords": ["대기업"],
        "cuts": [
            {"beat": "훅", "seg_ids": ["t1"], "broll_marker": None},
            {"beat": "라스트 답", "seg_ids": ["t2"], "broll_marker": None},
        ],
    }


@pytest.fixture
def style_preset():
    return load_style(Path(__file__).parent.parent / "styles" / "done.yaml")
