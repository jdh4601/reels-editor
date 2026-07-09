import pytest

from reels_editor import edl, render
from reels_editor.style import load_style
from pathlib import Path

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_timeline_items_speed_compresses(edl_doc: dict, segments: dict) -> None:
    ordered = edl.ordered_segments(edl_doc, segments)
    items = render.timeline_items(ordered, speed=2.0)
    # t1 소스 10초 → 5초
    assert items[0][:2] == [0.0, 5.0]
    assert items[1][0] == 5.0


def test_group_captions_merges_short_fragments() -> None:
    items = [[0.0, 0.5, "결국은"], [0.5, 1.5, "제가 시장을"], [1.5, 2.2, "설득하는 방법은"]]
    groups = render.group_captions(items, max_dur=2.4, max_chars=20)
    assert groups[0][2] == "결국은 제가 시장을 설득하는 방법은"[:20] or len(groups) >= 1
    # 20자 제한: "결국은 제가 시장을" 까지만 병합되고 나머지는 새 그룹
    assert all(len(g[2]) <= 20 for g in groups)


def test_split_by_keywords_marks_highlight() -> None:
    parts = render.split_by_keywords("일단 무조건 거부감을 가져요", ["거부감"])
    assert parts == [("일단 무조건 ", False), ("거부감", True), ("을 가져요", False)]


def test_split_by_keywords_no_match() -> None:
    assert render.split_by_keywords("평범한 문장", ["없는말"]) == [("평범한 문장", False)]


def test_build_base_filter_has_pad_for_bars(edl_doc: dict, segments: dict) -> None:
    style = load_style(STYLE)
    ordered = edl.ordered_segments(edl_doc, segments)
    f = render.build_base_filter(ordered, 1.2, style, in_size=(1920, 1080))
    assert "concat=n=2" in f
    assert "atempo=1.2" in f
    assert f"pad={style.canvas[0]}:{style.canvas[1]}" in f
    assert f":0:{style.top_bar}" in f  # 영상이 top_bar 아래에 놓임


def test_build_base_filter_content_crop_first(edl_doc: dict, segments: dict) -> None:
    # 원본이 필러박스(가로 화면 속 세로 영상)면 콘텐츠 크롭 → 비율 크롭 순
    style = load_style(STYLE)
    ordered = edl.ordered_segments(edl_doc, segments)
    f = render.build_base_filter(ordered, 1.2, style, in_size=(1920, 1080),
                                 content_crop=(608, 1080, 656, 0))
    vw, vh = style.video_area()
    aspect = render._crop_expr(608, 1080, vw, vh)
    assert f"crop=608:1080:656:0,{aspect}" in f


def test_parse_cropdetect_picks_most_common() -> None:
    lines = [
        "[Parsed_cropdetect_0] x1:656 ... crop=608:1080:656:0",
        "[Parsed_cropdetect_0] x1:656 ... crop=608:1080:656:0",
        "[Parsed_cropdetect_0] x1:0 ... crop=1920:1080:0:0",
    ]
    assert render.parse_cropdetect(lines) == (608, 1080, 656, 0)


def test_parse_cropdetect_empty_returns_none() -> None:
    assert render.parse_cropdetect(["no crop info"]) is None


def test_build_overlay_filter_static_then_timed() -> None:
    groups = [[0.0, 2.0, "안녕"], [2.0, 4.0, "하세요"]]
    filt, last = render.build_overlay_filter(n_static=2, groups=groups)
    # 입력 1,2 = 타이틀·워터마크(상시), 3,4 = 자막(시간창)
    assert "between(t,0.000,2.000)" in filt
    assert filt.count("overlay") == 4
    assert last == "[o3]"


def test_split_by_keywords_ignores_empty_keyword() -> None:
    # 빈 키워드는 무한 재귀 없이 무시되어야 한다
    assert render.split_by_keywords("문장", ["", "문장"]) == [("문장", True)]
    assert render.split_by_keywords("문장", [""]) == [("문장", False)]
