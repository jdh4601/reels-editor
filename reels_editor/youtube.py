"""YouTube 영상과 YouTube 제공 자막을 로컬 편집 소스로 준비한다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, urlparse

from reels_editor.timebase import US

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_MEDIA_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})


class YouTubeSourceError(RuntimeError):
    """YouTube 소스를 편집 입력으로 만들지 못했을 때의 사용자 표시 오류."""


class _YoutubeDL(Protocol):
    def __enter__(self) -> _YoutubeDL: ...
    def __exit__(self, *args: object) -> None: ...
    def extract_info(self, url: str, *, download: bool) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CaptionTrack:
    language: str
    kind: str


@dataclass(frozen=True)
class YouTubeSource:
    video_path: Path
    segments: dict[str, Any]
    title: str
    video_id: str
    source_url: str
    transcript_path: Path
    transcript_language: str
    transcript_kind: str
    thumbnail_url: str = ""


def validate_youtube_url(url: str) -> str:
    normalized = url.strip()
    try:
        parsed = urlparse(normalized)
    except ValueError as exc:
        raise YouTubeSourceError("올바른 YouTube 링크를 입력하세요.") from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    is_youtube = hostname in YOUTUBE_HOSTS or hostname.endswith(".youtube.com")
    if parsed.scheme not in {"http", "https"} or not is_youtube:
        raise YouTubeSourceError("youtube.com 또는 youtu.be 영상 링크만 사용할 수 있습니다.")
    if not parsed.path or parsed.path == "/":
        raise YouTubeSourceError("영상이 포함된 YouTube 링크를 입력하세요.")
    return normalized


def video_id_from_url(url: str) -> str | None:
    """Return a stable video ID for the common YouTube URL variants."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    parts = [part for part in parsed.path.split("/") if part]
    if hostname == "youtu.be":
        return parts[0] if parts else None
    if hostname not in YOUTUBE_HOSTS and not hostname.endswith(".youtube.com"):
        return None
    if parsed.path.rstrip("/") == "/watch":
        return next(iter(parse_qs(parsed.query).get("v", [])), None) or None
    if len(parts) >= 2 and parts[0] in {"embed", "live", "shorts"}:
        return parts[1]
    return None


def thumbnail_url_for_video(video_id: str | None) -> str | None:
    normalized = str(video_id or "").strip()
    if not normalized:
        return None
    return f"https://i.ytimg.com/vi/{normalized}/hqdefault.jpg"


def _thumbnail_url(info: dict[str, Any], video_id: str) -> str:
    direct = str(info.get("thumbnail") or "").strip()
    if direct:
        return direct
    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict):
                candidate = str(item.get("url") or "").strip()
                if candidate:
                    return candidate
    return thumbnail_url_for_video(video_id) or ""


def load_cached_youtube_source(
    source_dir: Path,
    source_url: str,
    *,
    expected_video_id: str | None = None,
    fallback_title: str = "YouTube 인터뷰",
) -> YouTubeSource | None:
    """Load a complete prior download, or return ``None`` for a partial cache."""
    try:
        segments_payload = json.loads((source_dir / "segments.json").read_text(encoding="utf-8"))
        if not isinstance(segments_payload, dict) or not isinstance(segments_payload.get("segments"), list):
            return None
        if not segments_payload["segments"]:
            return None
        video_path = _find_downloaded_video(source_dir)
        language = str(segments_payload.get("transcript_language") or "").strip()
        kind = str(segments_payload.get("transcript_kind") or "").strip()
        if not language or not kind:
            return None
        transcript_path = _find_transcript(source_dir, language)

        info: dict[str, Any] = {}
        info_path = source_dir / "source.info.json"
        if info_path.is_file():
            loaded_info = json.loads(info_path.read_text(encoding="utf-8"))
            if isinstance(loaded_info, dict):
                info = loaded_info
        cached_video_id = str(info.get("id") or expected_video_id or "").strip()
        if not cached_video_id:
            return None
        if expected_video_id and cached_video_id != expected_video_id:
            return None

        segments = dict(segments_payload)
        segments["video_path"] = str(video_path)
        segments.setdefault("source_title", str(info.get("title") or fallback_title).strip())
        segments.setdefault(
            "source_channel",
            str(info.get("channel") or info.get("uploader") or "").strip(),
        )
        return YouTubeSource(
            video_path=video_path,
            segments=segments,
            title=str(info.get("title") or fallback_title).strip() or fallback_title,
            video_id=cached_video_id,
            source_url=source_url,
            transcript_path=transcript_path,
            transcript_language=language,
            transcript_kind=kind,
            thumbnail_url=_thumbnail_url(info, cached_video_id),
        )
    except (OSError, ValueError, json.JSONDecodeError, YouTubeSourceError):
        return None


def select_caption_track(
    info: dict[str, Any],
    preferred_languages: tuple[str, ...] = ("en", "ko"),
) -> CaptionTrack:
    sources = (
        ("manual", _caption_languages(info.get("subtitles"))),
        ("automatic", _caption_languages(info.get("automatic_captions"))),
    )
    reported_language = str(info.get("language") or "").strip().lower()
    reported_base = reported_language.split("-", 1)[0]

    # 자동 자막 원본은 ``en-orig``처럼 표시될 수 있다. 번역 트랙보다
    # 화자의 실제 언어를 먼저 사용해야 의미와 타임코드가 가장 정확하다.
    for kind, languages in sources:
        original = next(
            (
                language
                for language in languages
                if language.lower().endswith("-orig")
                and (not reported_base or language.lower().split("-", 1)[0] == reported_base)
            ),
            None,
        )
        if original:
            return CaptionTrack(original, kind)

    for preferred in (reported_language, reported_base, *preferred_languages):
        if not preferred:
            continue
        for kind, languages in sources:
            match = _language_match(languages, preferred)
            if match:
                return CaptionTrack(match, kind)
    for kind, languages in sources:
        if languages:
            return CaptionTrack(languages[0], kind)
    raise YouTubeSourceError(
        "이 영상에는 YouTube에서 제공하는 자막이 없습니다. "
        "YouTube 스튜디오에서 자막을 만든 뒤 다시 시도하세요."
    )


def parse_json3_transcript(
    payload: dict[str, Any],
    *,
    video_path: Path,
    duration_s: float | None = None,
) -> dict[str, Any]:
    cues: list[tuple[int, int, str]] = []
    events = payload.get("events", [])
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        text = _normalize_caption_text(
            "".join(str(segment.get("utf8", "")) for segment in event["segs"] if isinstance(segment, dict))
        )
        start_ms = _non_negative_int(event.get("tStartMs"))
        duration_ms = _non_negative_int(event.get("dDurationMs"))
        cues.append((start_ms, start_ms + duration_ms, text))

    if not any(text for _start, _end, text in cues):
        raise YouTubeSourceError("YouTube 자막 파일에서 읽을 수 있는 대사를 찾지 못했습니다.")

    video_end_ms = round(duration_s * 1000) if duration_s and duration_s > 0 else None
    segments: list[dict[str, Any]] = []
    for index, (start_ms, raw_end_ms, text) in enumerate(cues):
        if not text:
            continue
        next_start_ms = cues[index + 1][0] if index + 1 < len(cues) else None
        end_ms = raw_end_ms
        if next_start_ms is not None and next_start_ms > start_ms:
            end_ms = min(end_ms, next_start_ms) if end_ms > start_ms else next_start_ms
        if end_ms <= start_ms:
            end_ms = next_start_ms or start_ms + 1000
        if video_end_ms is not None:
            end_ms = min(end_ms, video_end_ms)
        if end_ms <= start_ms:
            continue
        segments.append({
            "id": f"yt-{len(segments) + 1:05d}",
            "text": text,
            "timeline_start_us": start_ms * 1000,
            "timeline_end_us": end_ms * 1000,
            "source_start_us": start_ms * 1000,
            "source_end_us": end_ms * 1000,
            "speed": 1.0,
        })

    if not segments:
        raise YouTubeSourceError("YouTube 자막의 타임코드를 영상 구간으로 변환하지 못했습니다.")
    return {
        "video_material_id": "youtube-source",
        "video_path": str(video_path),
        "video_duration_us": round(duration_s * US) if duration_s else None,
        "fps": None,
        "segments": segments,
    }


def download_youtube_source(
    url: str,
    output_dir: Path,
    *,
    progress_cb: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    ydl_factory: Callable[[dict[str, Any]], _YoutubeDL] | None = None,
) -> YouTubeSource:
    source_url = validate_youtube_url(url)
    output_dir.mkdir(parents=True, exist_ok=True)
    factory = ydl_factory or _default_ydl_factory

    try:
        with factory({"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(source_url, download=False)
    except YouTubeSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 - yt-dlp errors are normalized at this boundary
        raise YouTubeSourceError(f"YouTube 영상 정보를 가져오지 못했습니다: {exc}") from exc

    if info.get("_type") == "playlist":
        raise YouTubeSourceError("재생목록이 아닌 YouTube 영상 한 개의 링크를 입력하세요.")
    track = select_caption_track(info)
    title = str(info.get("title") or "YouTube 인터뷰").strip()
    video_id = str(info.get("id") or "youtube").strip()
    duration_s = _positive_float(info.get("duration"))

    def progress_hook(event: dict[str, Any]) -> None:
        if cancelled and cancelled():
            raise YouTubeSourceError("YouTube 다운로드가 취소되었습니다.")
        if not progress_cb:
            return
        if event.get("status") == "finished":
            progress_cb(1.0)
            return
        downloaded = _positive_float(event.get("downloaded_bytes")) or 0.0
        total = _positive_float(event.get("total_bytes")) or _positive_float(event.get("total_bytes_estimate"))
        if total:
            progress_cb(max(0.0, min(downloaded / total, 0.99)))

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "source.%(ext)s"),
        "writesubtitles": track.kind == "manual",
        "writeautomaticsub": track.kind == "automatic",
        "subtitleslangs": [track.language],
        "subtitlesformat": "json3",
        "writeinfojson": True,
        "progress_hooks": [progress_hook],
    }
    try:
        with factory(options) as ydl:
            ydl.extract_info(source_url, download=True)
    except YouTubeSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 - yt-dlp errors are normalized at this boundary
        raise YouTubeSourceError(f"YouTube 영상 또는 자막 다운로드에 실패했습니다: {exc}") from exc

    video_path = _find_downloaded_video(output_dir)
    transcript_path = _find_transcript(output_dir, track.language)
    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise YouTubeSourceError(f"다운로드한 YouTube 자막을 읽지 못했습니다: {exc}") from exc
    segments = parse_json3_transcript(transcript, video_path=video_path, duration_s=duration_s)
    segments["transcript_language"] = track.language
    segments["transcript_kind"] = track.kind
    segments["source_title"] = title
    segments["source_channel"] = str(info.get("channel") or info.get("uploader") or "").strip()
    (output_dir / "transcript.txt").write_text(
        "\n".join(_transcript_line(item) for item in segments["segments"]) + "\n",
        encoding="utf-8",
    )
    (output_dir / "segments.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return YouTubeSource(
        video_path=video_path,
        segments=segments,
        title=title,
        video_id=video_id,
        source_url=source_url,
        transcript_path=transcript_path,
        transcript_language=track.language,
        transcript_kind=track.kind,
        thumbnail_url=_thumbnail_url(info, video_id),
    )


def _default_ydl_factory(options: dict[str, Any]) -> _YoutubeDL:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:  # pragma: no cover - dependency packaging failure
        raise YouTubeSourceError("yt-dlp가 설치되지 않았습니다. 앱을 다시 설치하거나 업데이트하세요.") from exc
    return YoutubeDL(options)


def _caption_languages(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [
        str(language)
        for language, formats in value.items()
        if language != "live_chat" and isinstance(formats, list) and formats
    ]


def _language_match(languages: list[str], preferred: str) -> str | None:
    preferred_lower = preferred.lower()
    for language in languages:
        if language.lower() == preferred_lower:
            return language
    for language in languages:
        if language.lower().startswith(f"{preferred_lower}-"):
            return language
    return None


def _find_downloaded_video(output_dir: Path) -> Path:
    candidates = sorted(
        path for path in output_dir.glob("source.*")
        if path.is_file() and path.suffix.lower() in _MEDIA_SUFFIXES
    )
    if not candidates:
        raise YouTubeSourceError("다운로드가 끝났지만 로컬 영상 파일을 찾지 못했습니다.")
    return candidates[0]


def _find_transcript(output_dir: Path, language: str) -> Path:
    exact = output_dir / f"source.{language}.json3"
    if exact.is_file():
        return exact
    candidates = sorted(output_dir.glob("source.*.json3"))
    if not candidates:
        raise YouTubeSourceError("다운로드가 끝났지만 YouTube 자막 파일을 찾지 못했습니다.")
    return candidates[0]


def _normalize_caption_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u200b", " ")).strip()


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _transcript_line(segment: dict[str, Any]) -> str:
    total_s = int(segment["source_start_us"] // US)
    minutes, seconds = divmod(total_s, 60)
    return f"[{minutes:02d}:{seconds:02d}] {segment['text']}"
