import json
from pathlib import Path

from typer.testing import CliRunner

from reels_editor import cli

runner = CliRunner()
STYLE = Path(__file__).parent.parent / "reels_editor" / "resources" / "styles" / "default.yaml"


def test_preflight_ok() -> None:
    assert cli.preflight(STYLE) == []


def test_help_exposes_only_rerender_command() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "render" in result.output
    assert "make" not in result.output


def test_render_command_rerenders_workdir(tmp_path, segments, edl_doc, monkeypatch):
    _check_cli_delegate(tmp_path, segments, edl_doc, monkeypatch, 1)


def test_render_command_respects_title_option(tmp_path, segments, edl_doc, monkeypatch):
    _check_cli_delegate(tmp_path, segments, edl_doc, monkeypatch, 2)


def _check_cli_delegate(tmp_path, segments, edl_doc, monkeypatch, title_index):
    from reels_editor.jobs import JobService
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc))
    (tmp_path / "segments.json").write_text(json.dumps(segments))
    calls = []
    def verified(self, doc, source, destination, **kwargs):
        calls.append((doc, source, destination, kwargs))
        destination.write_bytes(b"verified")
        return destination
    monkeypatch.setattr(JobService, "render_workdir", verified)
    result = runner.invoke(cli.app, ["render", str(tmp_path), "--title", str(title_index)])
    assert result.exit_code == 0, result.output
    assert calls[0][0] == edl_doc and calls[0][1] == segments
    assert calls[0][3]["title"] == edl_doc["title_candidates"][title_index - 1]["text"]
    assert (tmp_path / f"reel-t{title_index}.mp4").read_bytes() == b"verified"


def test_cli_review_failure_does_not_claim_success(tmp_path, segments, edl_doc, monkeypatch):
    from reels_editor.jobs import JobService
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc))
    (tmp_path / "segments.json").write_text(json.dumps(segments))
    def fail(*args, **kwargs):
        raise ValueError("Independent review unavailable")
    monkeypatch.setattr(JobService, "render_workdir", fail)
    result = runner.invoke(cli.app, ["render", str(tmp_path)])
    assert result.exit_code == 1
    assert "Quality gate failed" in result.output
    assert not (tmp_path / "reel-t1.mp4").exists()
