from __future__ import annotations

import json
from pathlib import Path

import pytest

from reels_editor.youtube import (
    YouTubeSourceError,
    download_youtube_source,
    parse_json3_transcript,
    select_caption_track,
    validate_youtube_url,
)


def test_validate_youtube_url_accepts_video_hosts_and_rejects_other_sites() -> None:
    assert validate_youtube_url(" https://youtu.be/abc123 ") == "https://youtu.be/abc123"
    assert validate_youtube_url("https://www.youtube.com/watch?v=abc123").endswith("abc123")

    with pytest.raises(YouTubeSourceError, match="youtube.com"):
        validate_youtube_url("https://example.com/watch?v=abc123")


def test_select_caption_prefers_english_then_korean_fallback() -> None:
    manual = select_caption_track({
        "subtitles": {"en": [{"ext": "json3"}], "ko": [{"ext": "json3"}]},
        "automatic_captions": {"ko": [{"ext": "json3"}]},
    })
    automatic = select_caption_track({
        "subtitles": {},
        "automatic_captions": {"ko-KR": [{"ext": "json3"}]},
    })

    assert (manual.language, manual.kind) == ("en", "manual")
    assert (automatic.language, automatic.kind) == ("ko-KR", "automatic")


def test_select_caption_prefers_reported_original_track_over_translation() -> None:
    track = select_caption_track({
        "language": "en",
        "subtitles": {},
        "automatic_captions": {
            "ko": [{"ext": "json3"}],
            "en": [{"ext": "json3"}],
            "en-orig": [{"ext": "json3"}],
        },
    })

    assert (track.language, track.kind) == ("en-orig", "automatic")


def test_select_caption_requires_a_youtube_provided_transcript() -> None:
    with pytest.raises(YouTubeSourceError, match="자막이 없습니다"):
        select_caption_track({"subtitles": {}, "automatic_captions": {}})


def test_parse_json3_transcript_builds_source_timed_segments(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    segments = parse_json3_transcript(
        {
            "events": [
                {"tStartMs": 1250, "dDurationMs": 1750, "segs": [{"utf8": "처음 \n"}, {"utf8": "문장"}]},
                {"tStartMs": 3000, "dDurationMs": 0, "segs": [{"utf8": "두 번째 문장"}]},
                {"tStartMs": 4500, "dDurationMs": 1000, "segs": [{"utf8": "   "}]},
            ]
        },
        video_path=video,
        duration_s=5.0,
    )

    assert segments["video_path"] == str(video)
    assert segments["video_duration_us"] == 5_000_000
    assert segments["segments"] == [
        {
            "id": "yt-00001",
            "text": "처음 문장",
            "timeline_start_us": 1_250_000,
            "timeline_end_us": 3_000_000,
            "source_start_us": 1_250_000,
            "source_end_us": 3_000_000,
            "speed": 1.0,
        },
        {
            "id": "yt-00002",
            "text": "두 번째 문장",
            "timeline_start_us": 3_000_000,
            "timeline_end_us": 4_500_000,
            "source_start_us": 3_000_000,
            "source_end_us": 4_500_000,
            "speed": 1.0,
        },
    ]


class _FakeYoutubeDL:
    def __init__(self, options: dict, info: dict, output_dir: Path) -> None:
        self.options = options
        self.info = info
        self.output_dir = output_dir

    def __enter__(self) -> _FakeYoutubeDL:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def extract_info(self, _url: str, *, download: bool) -> dict:
        if download:
            (self.output_dir / "source.mp4").write_bytes(b"video")
            (self.output_dir / "source.en.json3").write_text(
                json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Startups are hard"}]}]}),
                encoding="utf-8",
            )
            for hook in self.options.get("progress_hooks", []):
                hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
                hook({"status": "finished"})
        return self.info


def test_download_youtube_source_persists_video_raw_transcript_and_segments(tmp_path: Path) -> None:
    info = {
        "id": "abc123",
        "title": "창업가 인터뷰",
        "duration": 3600,
        "language": "en",
        "subtitles": {"en": [{"ext": "json3"}]},
        "automatic_captions": {},
    }
    options_seen: list[dict] = []
    progress: list[float] = []

    def factory(options: dict) -> _FakeYoutubeDL:
        options_seen.append(options)
        return _FakeYoutubeDL(options, info, tmp_path)

    source = download_youtube_source(
        "https://www.youtube.com/watch?v=abc123",
        tmp_path,
        progress_cb=progress.append,
        ydl_factory=factory,
    )

    assert source.video_path == tmp_path / "source.mp4"
    assert source.title == "창업가 인터뷰"
    assert source.transcript_language == "en"
    assert source.transcript_kind == "manual"
    assert source.segments["transcript_language"] == "en"
    assert source.segments["segments"][0]["text"] == "Startups are hard"
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == "[00:00] Startups are hard\n"
    assert json.loads((tmp_path / "segments.json").read_text(encoding="utf-8"))["video_path"] == str(tmp_path / "source.mp4")
    assert options_seen[1]["writesubtitles"] is True
    assert options_seen[1]["writeautomaticsub"] is False
    assert progress == [0.5, 1.0]
