from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reels_editor.source_cache import prepare_selected_source, selected_ranges
from reels_editor.timebase import US


def sample():
    segments = {"video_path": "/missing/source.mp4", "video_duration_us": 6 * US,
                "segments": [{"id": "a", "text": "First", "source_start_us": 800_000,
                              "source_end_us": 1_200_000},
                             {"id": "b", "text": "Last", "source_start_us": 4_500_000,
                              "source_end_us": 5_000_000}]}
    doc = {"cuts": [{"seg_ids": ["a", "b"]}]}
    return doc, segments


def test_ranges_merge_and_clamp_at_source_end():
    doc, segments = sample()
    assert selected_ranges(doc, segments) == [(550_000, 1_450_000), (4_250_000, 5_250_000)]
    segments["segments"][1].update(source_start_us=1_300_000, source_end_us=6 * US)
    assert selected_ranges(doc, segments) == [(550_000, 6 * US)]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_exact_sections_pack_remap_and_reuse_with_real_ffmpeg(tmp_path: Path):
    doc, segments = sample()
    downloads = []
    def downloader(url, directory, start, end, **kwargs):
        downloads.append((start, end))
        out = directory / "source.mp4"
        # Distinct color and tone prove each mapped cut uses its own source.
        color = "red" if start < US else "blue"
        frequency = 440 if start < US else 880
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color={color}:s=160x90:r=30", "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:sample_rate=48000", "-t", str((end-start)/US),
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)], check=True)
        return out
    video, mapped = prepare_selected_source("https://youtu.be/abc123", segments, doc, tmp_path,
                                            cancelled=lambda: False, downloader=downloader)
    assert len(downloads) == 2
    assert 1.8 * US <= mapped["video_duration_us"] <= 2.1 * US
    assert mapped["segments"][0]["source_start_us"] == 250_000
    assert mapped["segments"][1]["source_start_us"] < 1.3 * US
    assert mapped["segments"][1]["original_source_start_us"] == 4_500_000
    assert segments["segments"][1]["source_start_us"] == 4_500_000
    for item, dominant in zip(mapped["segments"], (0, 2)):
        frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(item["source_start_us"]/US),
                                "-i", str(video), "-frames:v", "1", "-vf", "scale=1:1",
                                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               check=True, capture_output=True).stdout
        assert frame[dominant] > 200 and frame[1] < 50
    second, again = prepare_selected_source("https://youtube.com/watch?v=abc123", segments, doc, tmp_path,
                                            cancelled=lambda: False, downloader=downloader)
    assert second == video and again == mapped and len(downloads) == 2
    # Another reel selecting just one section also reuses its download.
    prepare_selected_source("https://youtu.be/abc123", segments, {"cuts": [{"seg_ids": ["b"]}]}, tmp_path,
                            cancelled=lambda: False, downloader=downloader)
    assert len(downloads) == 2
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], check=True)


def test_cancelled_cache_wait_does_not_download(tmp_path: Path):
    doc, segments = sample()
    with pytest.raises(RuntimeError, match="취소"):
        prepare_selected_source("https://youtu.be/abc123", segments, doc, tmp_path,
                                cancelled=lambda: True)


def test_section_download_refreshes_streams_and_saves_redacted_diagnostics(tmp_path, monkeypatch):
    from reels_editor import source_cache
    extracts, commands = [], []
    class YDL:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def extract_info(self, url, *, download):
            extracts.append(download)
            return {'requested_formats': [
                {'url': f'https://video.test/stream?signature={len(extracts)}', 'vcodec': 'h264', 'acodec': 'none'},
                {'url': 'https://audio.test/stream', 'vcodec': 'none', 'acodec': 'aac'}]}
    monkeypatch.setattr(source_cache.youtube, '_default_ydl_factory', lambda _options: YDL())
    monkeypatch.setattr(source_cache.time, 'sleep', lambda _seconds: None)
    def run(args, **kwargs):
        commands.append(args)
        if len(commands) == 1:
            return subprocess.CompletedProcess(args, 8, '', 'Error opening https://video.test/stream?signature=secret HTTP 403')
        Path(args[-1]).write_bytes(b'video')
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(source_cache.processes, 'run', run)
    output = source_cache.download_section('https://youtu.be/abc123', tmp_path, US, 3*US, cancelled=lambda: False)
    assert output.read_bytes() == b'video'
    assert extracts == [False, False]
    assert 'signature=2' in ' '.join(commands[1])
    assert '0:v:0?' in commands[0] and '1:a:0?' in commands[0]
    assert 'secret' not in (tmp_path/'download-error.txt').read_text()
    assert 'HTTP 403' in (tmp_path/'download-error.txt').read_text()


def test_cancelled_section_download_does_not_extract(tmp_path, monkeypatch):
    from reels_editor import source_cache
    monkeypatch.setattr(source_cache.youtube, '_default_ydl_factory', lambda _opts: pytest.fail('must not extract'))
    with pytest.raises(RuntimeError, match='취소'):
        source_cache.download_section('https://youtu.be/abc123', tmp_path, 0, US, cancelled=lambda: True)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_section_downloader_exact_cut_with_real_http_ffmpeg(tmp_path, monkeypatch):
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from reels_editor import source_cache
    source = tmp_path/'original.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=30',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '3',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-movflags', '+faststart',
                    str(source)], check=True)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    class YDL:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def extract_info(self, _url, *, download):
            return {'url': f'http://127.0.0.1:{server.server_port}/original.mp4',
                    'vcodec': 'h264', 'acodec': 'aac', 'http_headers': {'User-Agent': 'reels-test'}}
    monkeypatch.setattr(source_cache.youtube, '_default_ydl_factory', lambda _opts: YDL())
    try:
        out = source_cache.download_section('https://youtu.be/abc123', tmp_path/'section',
                                            800_000, 1_700_000, cancelled=lambda: False)
        assert abs(source_cache._duration_us(out)-900_000) < 100_000
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name',
                                '-of', 'csv=p=0', str(out)], capture_output=True, text=True, check=True)
        assert 'h264' in probe.stdout and 'aac' in probe.stdout
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(out), '-f', 'null', '-'], check=True)
    finally:
        server.shutdown()
        server.server_close()
