from __future__ import annotations

from pathlib import Path
import subprocess

from reels_editor import voice_isolation


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_isolate_voice_posts_multipart_audio_and_writes_response(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "speech.wav"
    source.write_bytes(b"wave-data")
    output = tmp_path / "isolated.mp3"
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = request.data
        seen["timeout"] = timeout
        return _Response(b"clean-audio")

    monkeypatch.setattr(voice_isolation, "urlopen", fake_urlopen)

    voice_isolation.isolate_voice(source, output, api_key="xi-secret", timeout_s=45)

    assert output.read_bytes() == b"clean-audio"
    assert seen["url"] == "https://api.elevenlabs.io/v1/audio-isolation"
    assert seen["headers"]["Xi-api-key"] == "xi-secret"
    assert seen["headers"]["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'filename="speech.wav"' in seen["body"]
    assert b"wave-data" in seen["body"]
    assert b"xi-secret" not in seen["body"]
    assert seen["timeout"] == 45


def test_enhance_video_reuses_isolated_audio_cache(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    calls = {"isolate": 0, "replace": 0}

    def fake_extract(_video: Path, audio: Path) -> None:
        audio.write_bytes(b"same-pcm-audio")

    def fake_isolate(_source: Path, output: Path, *, api_key: str, timeout_s: float) -> Path:
        assert api_key == "xi-key"
        calls["isolate"] += 1
        output.write_bytes(b"isolated")
        return output

    def fake_replace(_video: Path, audio: Path, output: Path) -> None:
        calls["replace"] += 1
        output.write_bytes(b"muxed:" + audio.read_bytes())

    monkeypatch.setattr(voice_isolation, "extract_audio", fake_extract)
    monkeypatch.setattr(voice_isolation, "isolate_voice", fake_isolate)
    monkeypatch.setattr(voice_isolation, "replace_audio", fake_replace)

    first = voice_isolation.enhance_video(
        source, tmp_path / "first.mp4", cache_dir=tmp_path / "cache", api_key="xi-key"
    )
    second = voice_isolation.enhance_video(
        source, tmp_path / "second.mp4", cache_dir=tmp_path / "cache", api_key="xi-key"
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls == {"isolate": 1, "replace": 2}
    assert (tmp_path / "second.mp4").read_bytes() == b"muxed:isolated"


def test_replace_audio_applies_speech_enhancement_filter_chain(monkeypatch, tmp_path: Path) -> None:
    seen: list[str] = []

    def fake_run(args, **_kwargs):
        seen.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(voice_isolation.processes, "run", fake_run)

    voice_isolation.replace_audio(
        tmp_path / "source.mp4",
        tmp_path / "isolated.mp3",
        tmp_path / "enhanced.mp4",
    )

    filter_chain = seen[seen.index("-af") + 1]
    assert filter_chain == voice_isolation.SPEECH_ENHANCEMENT_FILTER
    assert "highpass=" in filter_chain
    assert "lowpass=" in filter_chain
    assert "afftdn=" in filter_chain
    assert "agate=" in filter_chain
    assert "acompressor=" in filter_chain
    assert "loudnorm=" in filter_chain


def test_extract_and_replace_audio_with_real_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    extracted = tmp_path / "speech.wav"
    output = tmp_path / "enhanced.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source),
        ],
        check=True,
    )

    voice_isolation.extract_audio(source, extracted)
    voice_isolation.replace_audio(source, extracted, output)

    streams = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate",
            "-of", "csv=p=0", str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "video" in streams
    assert "48000,audio" in streams or "audio,48000" in streams
