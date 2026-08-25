import json
from pathlib import Path

from typer.testing import CliRunner

from reels_editor import cli

runner = CliRunner()
STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_preflight_ok() -> None:
    assert cli.preflight(STYLE) == []


def test_help_exposes_only_rerender_command() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "render" in result.output
    assert "make" not in result.output


def test_render_command_rerenders_workdir(
    tmp_path: Path,
    segments: dict,
    edl_doc: dict,
    monkeypatch,
) -> None:
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    calls: dict = {}

    class FakeAssets:
        pass

    def fake_base(video_path, segs, doc, style, work_dir, speed, progress_cb=None):
        calls["base"] = (video_path, work_dir, speed)
        return FakeAssets()

    def fake_with_title(assets, title_text, keyword, style, out_path, **kwargs):
        calls["title"] = (title_text, keyword, out_path)
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_base_and_assets", fake_base)
    monkeypatch.setattr(cli.render, "render_with_title", fake_with_title)

    result = runner.invoke(cli.app, ["render", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert calls["title"][2] == tmp_path / "reel-t1.mp4"
    assert calls["title"][0] == edl_doc["title_candidates"][0]["text"]
    assert calls["base"][1] == tmp_path / ".render"


def test_render_command_respects_title_option(
    tmp_path: Path,
    segments: dict,
    edl_doc: dict,
    monkeypatch,
) -> None:
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    calls: dict = {}

    class FakeAssets:
        pass

    monkeypatch.setattr(cli.render, "render_base_and_assets", lambda *args, **kwargs: FakeAssets())

    def fake_with_title(assets, title_text, keyword, style, out_path, **kwargs):
        calls["title"] = title_text
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_with_title", fake_with_title)

    result = runner.invoke(cli.app, ["render", str(tmp_path), "--title", "2"])

    assert result.exit_code == 0, result.output
    assert calls["title"] == edl_doc["title_candidates"][1]["text"]
    assert (tmp_path / "reel-t2.mp4").exists()
