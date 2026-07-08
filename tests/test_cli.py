import json
from pathlib import Path

from typer.testing import CliRunner

from reels_editor import cli

runner = CliRunner()
STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_preflight_reports_missing_project() -> None:
    problems = cli.preflight("존재하지않는프로젝트", STYLE)
    assert any("CapCut" in p for p in problems)


def test_preflight_ok_without_project() -> None:
    # 이 머신에는 ffmpeg/claude/Pretendard가 있으므로 project 없이는 통과
    assert cli.preflight(None, STYLE) == []


def test_make_fails_fast_on_missing_project() -> None:
    result = runner.invoke(cli.app, ["make", "존재하지않는프로젝트"])
    assert result.exit_code == 1
    assert "CapCut" in result.output


def test_render_command_rerenders_workdir(tmp_path: Path, segments: dict,
                                          edl_doc: dict, monkeypatch) -> None:
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    called: dict = {}

    def fake_render(video_path, segs, doc, style, out_path, **kw):
        called["out"] = out_path
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_reel", fake_render)
    # export_cuts는 실제 ffmpeg로 fixture의 가상 video_path(/tmp/footage.mp4)를
    # 열려고 시도해 실패한다 — 이 테스트는 render 배선만 검증하므로 별도 fake 처리.
    # (실제 컷 추출 성공 경로는 test_integration.py::test_export_cuts_per_beat에서 검증)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])
    result = runner.invoke(cli.app, ["render", str(tmp_path)])
    assert result.exit_code == 0
    assert called["out"] == tmp_path / "reel.mp4"


def test_render_command_clears_stale_cuts(tmp_path: Path, segments: dict,
                                          edl_doc: dict, monkeypatch) -> None:
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    stale = tmp_path / "cuts" / "999-옛컷.mp4"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    def fake_render(video_path, segs, doc, style, out_path, **kw):
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_reel", fake_render)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])
    result = runner.invoke(cli.app, ["render", str(tmp_path)])
    assert result.exit_code == 0
    assert not stale.exists()  # 이전 실행의 컷은 정리되어야 한다
