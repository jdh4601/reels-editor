"""reels-editor CLI — make(전체 파이프라인) / render(재렌더)."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import typer

from reels_editor import capcut, edl, export, gate, render, storyteller
from reels_editor.style import StylePreset, load_style

app = typer.Typer(help="창업가 인터뷰 → 30초 스토리텔링 릴스")
DEFAULT_STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def preflight(project: str | None, style_path: Path) -> list[str]:
    problems: list[str] = []
    for binname, hint in (("ffmpeg", "brew install ffmpeg"),
                          ("ffprobe", "brew install ffmpeg"),
                          ("claude", "Claude Code CLI 설치 필요")):
        if not shutil.which(binname):
            problems.append(f"{binname} 없음 — {hint}")
    try:
        load_style(style_path)
    except (FileNotFoundError, KeyError) as e:
        problems.append(f"스타일 로드 실패: {e}")
    if project is not None:
        try:
            pdir = capcut.find_project(project)
            segs = capcut.build_segments(capcut.load_project(pdir))
            if not segs["segments"]:
                problems.append("자동자막이 없습니다 — CapCut에서 Text → 자동자막을 먼저 생성하세요.")
        except (FileNotFoundError, ValueError, KeyError) as e:
            problems.append(str(e))
    return problems


def _fail_if_problems(problems: list[str]) -> None:
    if problems:
        for p in problems:
            typer.echo(f"✗ {p}")
        raise typer.Exit(1)


def _render_all(video: Path, segments: dict, edl_doc: dict, style: StylePreset,
                work: Path, speed: float) -> None:
    export.write_outputs(work, edl_doc, segments)
    render.render_reel(video, segments, edl_doc, style, work / "reel.mp4",
                       speed=speed, work_dir=work / ".render")
    ordered = edl.ordered_segments(edl_doc, segments)
    groups = render.group_captions([
        [a, b, render.apply_text_fixes(t, render.DEFAULT_TEXT_FIXES)]
        for a, b, t in render.timeline_items(ordered, speed)])
    export.write_srt(groups, work / "reel.srt")
    cuts_dir = work / "cuts"
    if cuts_dir.is_dir():
        for old in cuts_dir.glob("*.mp4"):  # 이전 실행 잔존 컷이 새 EDL과 어긋나는 것 방지
            old.unlink()
    export.export_cuts(video, edl_doc, segments, cuts_dir, speed)
    typer.echo(f"✅ 완료: {work / 'reel.mp4'}")
    typer.echo(f"   수정용 재료: {work}/reel.srt, edl.json, cuts/")


@app.command()
def make(project: str,
         speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
         duration: int = typer.Option(30, help="목표 길이(초)"),
         style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
         no_ui: bool = typer.Option(False, "--no-ui", help="터미널 게이트 사용"),
         out: Path = typer.Option(Path("out"), help="산출물 루트")) -> None:
    """CapCut 프로젝트 → 대본 게이트 → 30초 릴스."""
    _fail_if_problems(preflight(project, style))
    preset = load_style(style)
    spd = speed if speed is not None else preset.speed
    pdir = capcut.find_project(project)
    segments = capcut.build_segments(capcut.load_project(pdir))
    video = Path(segments["video_path"])
    work = out / f"{pdir.name}-{dt.date.today():%Y%m%d}"
    work.mkdir(parents=True, exist_ok=True)

    feedback: str | None = None
    while True:
        typer.echo("🧠 대본 생성 중 (claude)…")
        edl_doc = storyteller.generate_script(segments, duration, feedback,
                                              raw_dump=work / "llm_raw.txt")
        dur = edl.estimate_duration_s(edl_doc, segments, spd)
        if no_ui:
            decision = gate.run_gate_terminal(edl_doc, segments, dur, duration)
        else:
            thumbs = gate.extract_thumbs(video, edl_doc, segments, work / ".thumbs")
            html = gate.build_gate_html(edl_doc, segments, thumbs, dur, duration)
            decision = gate.run_gate(html)
        if decision.action == "approve":
            edl_doc["selected_title"] = decision.title_index
            break
        feedback = decision.feedback

    _render_all(video, segments, edl_doc, preset, work, spd)


@app.command("render")
def render_cmd(workdir: Path,
               speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
               style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml")) -> None:
    """수동 수정한 edl.json으로 재렌더 (게이트·LLM 없이)."""
    edl_path, seg_path = workdir / "edl.json", workdir / "segments.json"
    if not edl_path.is_file() or not seg_path.is_file():
        typer.echo(f"✗ {workdir}에 edl.json/segments.json이 없습니다.")
        raise typer.Exit(1)
    _fail_if_problems(preflight(None, style))
    preset = load_style(style)
    spd = speed if speed is not None else preset.speed
    edl_doc = json.loads(edl_path.read_text(encoding="utf-8"))
    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    errs = edl.validate_edl(edl_doc, segments)
    if errs:
        typer.echo("✗ EDL 검증 실패:\n" + "\n".join(errs))
        raise typer.Exit(1)
    _render_all(Path(segments["video_path"]), segments, edl_doc, preset,
                workdir, spd)


if __name__ == "__main__":
    app()
