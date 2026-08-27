import subprocess
import sys
import threading
import unicodedata
from types import SimpleNamespace

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
    items = [[0.0, 0.5, "결국은"], [0.5, 1.5, "제가 시장을"], [1.5, 2.2, "설득하는 것입니다."]]
    groups = render.group_captions(items, max_dur=2.4, max_chars=20)
    assert [group[2] for group in groups] == ["결국은 제가 시장을 설득하는 것입니다"]


def test_group_captions_splits_long_sentence_at_semantic_clauses() -> None:
    groups = render.group_captions(
        [[0.0, 4.0, "고객이 원하는 것을 모르고 제품부터 만들면 정말 오래 헤매게 됩니다"]],
        max_chars=20,
    )

    assert [group[2] for group in groups] == [
        "고객이 원하는 것을 모르고",
        "제품부터 만들면",
        "정말 오래 헤매게 됩니다",
    ]
    assert groups[0][0] == 0.0
    assert groups[-1][1] == 4.0


def test_group_captions_splits_subscription_sentence_like_real_reel() -> None:
    groups = render.group_captions([[
        0.0,
        6.0,
        "왜냐하면 이제 우리는 구독 사업이었고, 그 말은 선불로 받는 돈은 줄고 나중에 받는 돈은 늘어난다는 뜻이었죠.",
    ]])

    assert [group[2] for group in groups] == [
        "왜냐하면 이제 우리는 구독 사업이었고",
        "그 말은 선불로 받는 돈은 줄고",
        "나중에 받는 돈은 늘어난다는 뜻이었죠",
    ]
    assert all(len(group[2]) <= 22 for group in groups)


def test_group_captions_never_mixes_start_of_next_sentence() -> None:
    groups = render.group_captions([
        [0.0, 1.0, "이 일을 형편없이 합니다."],
        [1.0, 1.4, "저도"],
        [1.4, 2.2, "처음에는 그랬습니다."],
    ])

    assert [group[2] for group in groups] == [
        "이 일을 형편없이 합니다",
        "저도 처음에는 그랬습니다",
    ]
    assert all("합니다 저도" not in group[2] for group in groups)


def test_group_captions_merges_semantic_fragment_even_with_period() -> None:
    groups = render.group_captions([
        [0.0, 0.4, "저도."],
        [0.4, 1.5, "처음에는 그랬습니다."],
    ])

    assert groups == [[0.0, 1.5, "저도 처음에는 그랬습니다"]]


def test_group_captions_splits_two_sentences_inside_one_youtube_cue() -> None:
    groups = render.group_captions([
        [0.0, 3.0, "형편없이 합니다. 저도 처음에는 그랬습니다."],
    ])

    assert [group[2] for group in groups] == [
        "형편없이 합니다",
        "저도 처음에는 그랬습니다",
    ]
    assert groups[0][0] == 0.0
    assert groups[-1][1] == 3.0


def test_group_captions_hides_commas_and_periods_only_in_final_text() -> None:
    groups = render.group_captions([
        [0.0, 1.2, "네, 맞습니다."],
        [1.2, 2.4, "정말일까요?"],
    ])

    assert [group[2] for group in groups] == ["네 맞습니다", "정말일까요?"]
    assert all("," not in group[2] and "." not in group[2] for group in groups)


def test_group_captions_keeps_ascii_quoted_sentence_together() -> None:
    groups = render.group_captions([
        [0.0, 0.8, '그는 "좋은 아이디어도'],
        [0.8, 1.7, '포기해야 합니다."'],
        [1.7, 2.5, "그래야 성장합니다."],
    ])

    assert [group[2] for group in groups] == [
        '그는 "좋은 아이디어도 포기해야 합니다"',
        "그래야 성장합니다",
    ]


def test_group_captions_splits_embedded_quote_at_sentence_boundaries() -> None:
    groups = render.group_captions([[
        0.0,
        3.0,
        '그는 "실패했습니다. 다시 시작했습니다."라고 말했습니다.',
    ]])

    assert len(groups) >= 2
    assert all(len(group[2]) <= 22 for group in groups)
    assert all(group[2].count('"') % 2 == 0 for group in groups)


def test_group_captions_balances_curly_quotes_after_display_split() -> None:
    groups = render.group_captions([
        [0.0, 0.8, "그는 “아무도 답을"],
        [0.8, 1.8, "몰랐습니다.”라고 말했습니다."],
    ])

    assert len(groups) >= 2
    assert all(len(group[2]) <= 20 for group in groups)
    assert all(group[2].count("“") == group[2].count("”") for group in groups)


def test_group_captions_splits_long_quote_without_unbalanced_quote_marks() -> None:
    groups = render.group_captions([[
        0.0,
        8.0,
        '"좋아 나는 존재하지 않는 무언가를 만들고 있어 만약 모두에게 제한 없이 열려면 계속 나아가야 해."',
    ]])

    assert len(groups) >= 3
    assert all(len(group[2]) <= 22 for group in groups)
    assert all('"' not in group[2] for group in groups)


def test_group_captions_rejects_unfinished_sentence_and_open_quote() -> None:
    with pytest.raises(ValueError, match="큰따옴표가 닫히지 않음"):
        render.group_captions([[0.0, 1.0, '그는 "좋은 아이디어도']])


def test_split_by_keywords_marks_highlight() -> None:
    parts = render.split_by_keywords("일단 무조건 거부감을 가져요", ["거부감"])
    assert parts == [("일단 무조건 ", False), ("거부감", True), ("을 가져요", False)]


def test_split_by_keywords_no_match() -> None:
    assert render.split_by_keywords("평범한 문장", ["없는말"]) == [("평범한 문장", False)]


def test_sparse_subtitle_highlights_are_rare_and_never_consecutive() -> None:
    groups = [[float(i), float(i + 1), f"핵심 고객 문제 {i}"] for i in range(12)]

    plan = render.sparse_subtitle_highlights(groups, ["핵심", "고객", "문제"])

    highlighted = [index for index, keywords in enumerate(plan) if keywords]
    assert len(highlighted) == 2
    assert all(len(plan[index]) == 1 for index in highlighted)
    assert all(right - left >= 3 for left, right in zip(highlighted, highlighted[1:]))


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
    crop = render.video_crop_box((608, 1080), style)
    assert f"crop=608:1080:656:0,crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}" in f


def test_video_crop_box_fits_source_to_nine_sixteen_canvas_without_extra_zoom() -> None:
    style = load_style(STYLE)

    crop = render.video_crop_box((1920, 1080), style)

    # 전체 출력은 9:16이고, 중앙 영상창은 원본을 추가 확대 없이 채운다.
    assert crop == render._center_crop_box(
        1920, 1080, *style.video_area())


def test_video_crop_box_moves_and_zooms_toward_left_speaker() -> None:
    style = load_style(STYLE)

    crop = render.video_crop_box((1920, 1080), style, focus_x=0.14, zoom=1.4)

    assert crop[0] < render.video_crop_box((1920, 1080), style)[0]
    assert crop[2] == 0


def test_video_crop_box_moves_up_to_preserve_speaker_headroom() -> None:
    style = load_style(STYLE)

    centered = render.video_crop_box((1920, 1080), style, zoom=1.4)
    speaker_safe = render.video_crop_box(
        (1920, 1080), style, focus_y=0.28, zoom=1.4
    )

    assert speaker_safe[3] < centered[3]
    assert speaker_safe[3] == 0


def test_build_base_filter_applies_focus_per_segment(edl_doc: dict, segments: dict) -> None:
    from reels_editor.speaker_focus import FocusPoint

    style = load_style(STYLE)
    ordered = edl.ordered_segments(edl_doc, segments)
    points = [
        FocusPoint(x=0.14, y=0.28, zoom=1.4),
        FocusPoint(x=0.86, y=0.42, zoom=1.4),
    ]

    filt = render.build_base_filter(
        ordered,
        1.2,
        style,
        in_size=(1920, 1080),
        focus_points=points,
    )

    left_crop = render.video_crop_box(
        (1920, 1080), style, focus_x=0.14, focus_y=0.28, zoom=1.4
    )
    right_crop = render.video_crop_box(
        (1920, 1080), style, focus_x=0.86, focus_y=0.42, zoom=1.4
    )
    assert f"crop={left_crop[0]}:{left_crop[1]}:{left_crop[2]}:{left_crop[3]}" in filt
    assert f"crop={right_crop[0]}:{right_crop[1]}:{right_crop[2]}:{right_crop[3]}" in filt
    assert "concat=n=2:v=1:a=1[v][a]" in filt


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


def test_select_video_encoder_enables_videotoolbox_on_supported_macos(
        monkeypatch: pytest.MonkeyPatch) -> None:
    render.select_video_encoder.cache_clear()
    monkeypatch.setenv("REELS_EDITOR_VIDEO_ENCODER", "h264_videotoolbox")
    monkeypatch.setattr(render.sys, "platform", "darwin")
    monkeypatch.setattr(render.shutil, "which", lambda name: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(
        render.processes,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=" V....D h264_videotoolbox VideoToolbox H.264 Encoder",
        ),
    )

    encoder = render.select_video_encoder()

    assert encoder.name == "h264_videotoolbox"
    assert "-allow_sw" in encoder.args
    render.select_video_encoder.cache_clear()


def test_select_video_encoder_can_force_software(monkeypatch: pytest.MonkeyPatch) -> None:
    render.select_video_encoder.cache_clear()
    monkeypatch.setenv("REELS_EDITOR_VIDEO_ENCODER", "libx264")

    assert render.select_video_encoder().name == "libx264"
    render.select_video_encoder.cache_clear()


def test_select_video_encoder_defaults_to_measured_fast_software(
        monkeypatch: pytest.MonkeyPatch) -> None:
    render.select_video_encoder.cache_clear()
    monkeypatch.delenv("REELS_EDITOR_VIDEO_ENCODER", raising=False)

    assert render.select_video_encoder().name == "libx264"
    render.select_video_encoder.cache_clear()


def test_encode_video_retries_with_libx264_when_videotoolbox_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        render,
        "select_video_encoder",
        lambda: render.VideoEncoder("h264_videotoolbox", ("-c:v", "h264_videotoolbox")),
    )

    def fake_ffmpeg(args: list[str]) -> None:
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("VideoToolbox unavailable")

    monkeypatch.setattr(render, "_ffmpeg", fake_ffmpeg)

    used = render._encode_video(["-i", "source.mp4"], ["out.mp4"])

    assert used.name == "libx264"
    assert "h264_videotoolbox" in calls[0]
    assert "libx264" in calls[1]


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


def test_render_assets_manifest_round_trips(tmp_path: Path) -> None:
    assets = render.RenderAssets(
        base=tmp_path / "base.mp4",
        wm_png=tmp_path / "wm.png",
        sub_pngs=[tmp_path / "subs" / "0.png"],
        groups=[[0.0, 1.0, "자막"]],
        work=tmp_path,
        keywords=["자막"],
    )

    restored = render.RenderAssets.read_manifest(
        assets.write_manifest(tmp_path / "assets.json")
    )

    assert restored == assets


def test_overlay_variant_subtitle_off_reuses_base_without_sub_inputs(
        tmp_path: Path, style_preset, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "base.mp4"
    wm = tmp_path / "wm.png"
    sub = tmp_path / "subs" / "0.png"
    sub.parent.mkdir()
    base.write_bytes(b"base")
    wm.write_bytes(b"wm")
    sub.write_bytes(b"sub")
    assets = render.RenderAssets(
        base=base,
        wm_png=wm,
        sub_pngs=[sub],
        groups=[[0.0, 1.0, "자막"]],
        work=tmp_path,
        keywords=["자막"],
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        render,
        "render_title_png",
        lambda *_args, **_kwargs: tmp_path / "title.png",
    )
    (tmp_path / "title.png").write_bytes(b"title")

    def fake_ffmpeg(args: list[str]) -> None:
        calls["args"] = args
        Path(args[-1]).write_bytes(b"variant")

    monkeypatch.setattr(render, "_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(
        render,
        "render_base_and_assets",
        lambda *a, **kw: pytest.fail("base render must not run for overlay variant"),
    )

    out = render.render_overlay_variant(
        assets,
        title_text="새 제목",
        keyword="새",
        style=style_preset,
        out_path=tmp_path / "variant.mp4",
        subtitles_enabled=False,
    )

    assert out.read_bytes() == b"variant"
    args = calls["args"]
    assert isinstance(args, list)
    assert str(base) in args
    assert str(sub) not in args
    assert args[-1].endswith(".part.mp4")
    assert not (tmp_path / ".variant.part.mp4").exists()


def test_overlay_variant_single_pass_uses_source_crop_audio_and_hardware_encoder(
        tmp_path: Path, style_preset, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    base_filter = tmp_path / "base-filter.txt"
    base_filter.write_text("[0:v]null[v];[0:a]anull[a]", encoding="utf-8")
    title = tmp_path / "title.png"
    watermark = tmp_path / "wm.png"
    title.write_bytes(b"title")
    watermark.write_bytes(b"watermark")
    assets = render.RenderAssets(
        base=source,
        wm_png=watermark,
        sub_pngs=[],
        groups=[],
        work=tmp_path,
        keywords=[],
        source=source,
        base_filter=base_filter,
        total_s=1.0,
    )
    calls: dict[str, list[str]] = {}

    monkeypatch.setattr(render, "render_title_png", lambda *_args, **_kwargs: title)
    monkeypatch.setattr(
        render,
        "select_video_encoder",
        lambda: render.VideoEncoder("h264_videotoolbox", ("-c:v", "h264_videotoolbox")),
    )

    def fake_ffmpeg(args: list[str]) -> None:
        calls["args"] = args
        Path(args[-1]).write_bytes(b"variant")

    monkeypatch.setattr(render, "_ffmpeg", fake_ffmpeg)

    out = render.render_overlay_variant(
        assets,
        title_text="새 제목",
        keyword="",
        style=style_preset,
        out_path=tmp_path / "single-pass.mp4",
        subtitles_enabled=False,
    )

    args = calls["args"]
    assert out.read_bytes() == b"variant"
    assert args.count(str(source)) == 1
    assert "[0:v]null[v];[0:a]anull[a]" in args[args.index("-filter_complex") + 1]
    assert args[args.index("-map") + 1] == "[vout]"
    assert "[a]" in args
    assert "h264_videotoolbox" in args


def test_variant_cache_key_changes_by_title_subtitle_and_style() -> None:
    base = render.variant_cache_key(
        storyline_id="s1",
        title_text="A",
        subtitles_enabled=True,
        style_hash_value="style",
    )

    assert base != render.variant_cache_key(
        storyline_id="s1",
        title_text="B",
        subtitles_enabled=True,
        style_hash_value="style",
    )
    assert base != render.variant_cache_key(
        storyline_id="s1",
        title_text="A",
        subtitles_enabled=False,
        style_hash_value="style",
    )
    assert base != render.variant_cache_key(
        storyline_id="s1",
        title_text="A",
        subtitles_enabled=True,
        style_hash_value="other",
    )
    assert base != render.variant_cache_key(
        storyline_id="s1",
        title_text="A",
        subtitles_enabled=True,
        style_hash_value="style",
        speaker_text="샘 알트만 (CEO of OpenAI)",
    )


def test_variant_cache_key_normalizes_canonically_equivalent_titles() -> None:
    composed = "가나다라마바"

    assert render.variant_cache_key(
        storyline_id="s1",
        title_text=composed,
        subtitles_enabled=True,
        style_hash_value="style",
    ) == render.variant_cache_key(
        storyline_id="s1",
        title_text=unicodedata.normalize("NFD", composed),
        subtitles_enabled=True,
        style_hash_value="style",
    )


def test_speaker_label_formats_name_and_role() -> None:
    assert render.speaker_label({
        "speaker": {
            "name": "샘 알트만",
            "company": "OpenAI",
            "role": "CEO",
            "evidence": "OpenAI CEO 샘 알트만",
        },
    }) == "샘 알트만 (OpenAI CEO)"
    assert render.speaker_label({
        "speaker": {
            "name": "김지영",
            "company": "마루",
            "role": "Founder",
            "evidence": "마루 창업자 김지영",
        },
    }) == "김지영 (마루 창업자)"
    assert render.speaker_label({
        "speaker": {
            "name": "박민수",
            "alternate_role": "investor",
            "evidence": "투자자 박민수",
        },
    }) == "박민수 (투자자)"
    assert render.speaker_label({
        "speaker": {"name": "샘 알트만", "role": "CEO of OpenAI"},
    }) == "샘 알트만"
    assert render.speaker_label({
        "speaker": {"name": "이서준", "role": "visionary"},
    }) == "이서준"
    assert render.speaker_label({}) == ""
