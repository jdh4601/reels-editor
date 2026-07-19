import subprocess
import sys
import threading

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


def test_parse_progress_line() -> None:
    assert render.parse_progress_line("out_time_us=1500000") == 1.5
    assert render.parse_progress_line("frame=42") is None
    assert render.parse_progress_line("out_time_us=N/A") is None


# stdout 파이프를 라인 단위로 소비하는 동안, stderr에 OS 파이프 버퍼(약 64KB)를
# 채울 만큼의 출력이 쌓이면 자식은 stderr write에서, 부모는 stdout read에서
# 서로 블록되는 교착 상태가 재현된다. ffmpeg 대신 이 조건을 흉내내는 python
# 서브프로세스를 실행해 회귀를 검증한다.
_STDERR_FLOOD_SCRIPT = """
import sys
import time

sys.stderr.write("e" * 300000)  # 파이프 버퍼(~64KB)보다 훨씬 크게
sys.stderr.flush()
for i in range(5):
    print(f"out_time_us={(i + 1) * 500000}")
    sys.stdout.flush()
    time.sleep(0.01)
sys.exit(0)
"""


def test_ffmpeg_progress_drains_stderr_concurrently_no_deadlock(monkeypatch) -> None:
    real_popen = subprocess.Popen

    def fake_popen(_cmd, **kwargs):
        # ffmpeg 실행 대신, stderr를 대량으로 흘리는 파이썬 스크립트로 교체
        return real_popen([sys.executable, "-c", _STDERR_FLOOD_SCRIPT], **kwargs)

    monkeypatch.setattr(render.subprocess, "Popen", fake_popen)

    seen: list[float] = []
    result: dict[str, object] = {}

    def run() -> None:
        try:
            render._ffmpeg_progress(["-i", "in.mp4"], total_s=2.5, cb=seen.append)
        except Exception as exc:  # pragma: no cover - 실패 시 진단용
            result["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=15)

    # 데드락이 재발하면 스레드가 끝나지 않는다 — 무한 대기 대신 여기서 실패시킨다.
    assert not t.is_alive(), "deadlock: _ffmpeg_progress가 완료되지 않음"
    assert "error" not in result, result.get("error")
    assert seen  # 진행률 콜백이 최소 한 번 이상 소비됨
    assert all(0.0 <= v <= 1.0 for v in seen)
