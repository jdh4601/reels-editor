"""게이트 HTML: 스토리라인 카드·조합 체크박스·설정 필드·경고 배지."""
from reels_editor.config import AppConfig
from reels_editor.gate_html import build_gate_html
from reels_editor.storyteller import StorylineResult


def _doc(title_texts):
    return {"story": {"five_lines": {"situation": "상황"}, "lens": "렌즈"},
            "title_candidates": [{"text": t, "keyword": t[:2]} for t in title_texts],
            "subtitle_keywords": ["키워드"],
            "cuts": [{"beat": "훅", "seg_ids": ["s1"]}]}


def _segments():
    return {"segments": [{"id": "s1", "text": "안녕하세요",
                          "source_start_us": 0, "source_end_us": 1_000_000}],
            "video_path": "v.mp4"}


def test_html_renders_combo_checkboxes_per_storyline_title() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc(["타이틀A", "타이틀B"])),
          StorylineResult(1, "반전형", _doc(["타이틀C"]))]
    html = build_gate_html(sl, _segments(), {}, {0: 29.0, 1: 31.0}, 30,
                           AppConfig(), {})
    for v in ("0-0", "0-1", "1-0"):
        assert f'name="combo" value="{v}"' in html
    assert 'name="regen" value="0"' in html
    assert "정면승부형" in html and "반전형" in html


def test_html_shows_failed_storyline_error() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc(["타이틀A"])),
          StorylineResult(1, "반전형", None, "boom 오류")]
    html = build_gate_html(sl, _segments(), {}, {0: 29.0}, 30, AppConfig(), {})
    assert "boom 오류" in html
    assert 'name="combo" value="1-0"' not in html   # 실패분엔 조합 없음


def test_html_settings_fields_reflect_config() -> None:
    cfg = AppConfig(provider="kimi", model="kimi-k2-0905-preview")
    html = build_gate_html(
        [StorylineResult(0, "정면승부형", _doc(["티"]))],
        _segments(), {}, {0: 30.0}, 30, cfg, {"kimi": "✓ 환경변수"})
    assert 'id="set-provider"' in html and 'id="set-sub_size"' in html
    assert "✓ 환경변수" in html
    assert 'id="preview-img"' in html
    assert 'id="set-n_storylines"' in html
    assert 'max="10"' in html


def test_html_duration_warning_badge() -> None:
    html = build_gate_html(
        [StorylineResult(0, "정면승부형", _doc(["티"]))],
        _segments(), {}, {0: 40.0}, 30, AppConfig(), {})
    assert "±10%" in html
