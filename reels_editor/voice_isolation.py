"""ElevenLabs Voice Isolator와 최종 MP4 오디오 교체 파이프라인."""
from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from reels_editor import processes


VOICE_ISOLATION_URL = "https://api.elevenlabs.io/v1/audio-isolation"
DEFAULT_TIMEOUT_S = 180.0
LOUDNESS_FILTER = "loudnorm=I=-16:LRA=7:TP=-1.5"


class VoiceIsolationError(RuntimeError):
    pass


@dataclass(frozen=True)
class IsolationResult:
    output_path: Path
    cache_hit: bool
    audio_hash: str


def _multipart_audio(path: Path, boundary: str) -> bytes:
    safe_name = path.name.replace('"', "")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="{safe_name}"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    return head + path.read_bytes() + tail


def isolate_voice(
    source: Path,
    output: Path,
    *,
    api_key: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Path:
    """WAV를 ElevenLabs에 보내고 반환된 격리 오디오를 원자적으로 저장한다."""
    if not api_key.strip():
        raise VoiceIsolationError("ElevenLabs API key가 비어 있습니다.")
    if not source.is_file():
        raise VoiceIsolationError(f"격리할 오디오 파일이 없습니다: {source}")

    boundary = f"reels-editor-{secrets.token_hex(16)}"
    request = Request(
        VOICE_ISOLATION_URL,
        data=_multipart_audio(source, boundary),
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            isolated = response.read()
    except HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise VoiceIsolationError(
            f"ElevenLabs Voice Isolator 요청 실패 (HTTP {exc.code}){suffix}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise VoiceIsolationError(f"ElevenLabs Voice Isolator 연결 실패: {exc}") from exc

    if not isolated:
        raise VoiceIsolationError("ElevenLabs Voice Isolator가 빈 오디오를 반환했습니다.")

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.stem}.{secrets.token_hex(6)}.part{output.suffix}")
    try:
        tmp.write_bytes(isolated)
        os.replace(tmp, output)
    finally:
        if tmp.exists():
            tmp.unlink()
    return output


def extract_audio(video: Path, output: Path) -> None:
    """API 품질을 위해 최종 영상의 오디오를 무손실 48kHz WAV로 추출한다."""
    _ffmpeg(
        [
            "-i", str(video),
            "-map", "0:a:0",
            "-vn",
            "-ar", "48000",
            "-c:a", "pcm_s16le",
            str(output),
        ],
        "오디오 추출",
    )


def replace_audio(video: Path, isolated_audio: Path, output: Path) -> None:
    """영상 스트림은 복사하고 격리 오디오만 정규화해 AAC로 다시 인코딩한다."""
    output.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        [
            "-i", str(video),
            "-i", str(isolated_audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-af", LOUDNESS_FILTER,
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-movflags", "+faststart",
            "-shortest",
            "-f", "mp4",
            str(output),
        ],
        "격리 오디오 결합",
    )


def enhance_video(
    video: Path,
    output: Path,
    *,
    cache_dir: Path,
    api_key: str,
) -> IsolationResult:
    """최종 영상 오디오를 격리하고 동일 PCM은 캐시해 API 재과금을 피한다."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, extracted_name = tempfile.mkstemp(prefix="voice-", suffix=".wav", dir=cache_dir)
    os.close(fd)
    extracted = Path(extracted_name)
    try:
        extract_audio(video, extracted)
        audio_hash = _sha256(extracted)
        cached = cache_dir / f"{audio_hash}.mp3"
        cache_hit = cached.is_file() and cached.stat().st_size > 0
        if not cache_hit:
            isolate_voice(extracted, cached, api_key=api_key, timeout_s=DEFAULT_TIMEOUT_S)
        replace_audio(video, cached, output)
        return IsolationResult(output, cache_hit=cache_hit, audio_hash=audio_hash)
    finally:
        if extracted.exists():
            extracted.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ffmpeg(args: list[str], action: str) -> None:
    result = processes.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        raise VoiceIsolationError(f"{action} 실패: {detail or 'ffmpeg 오류'}")
