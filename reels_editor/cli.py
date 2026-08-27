"""Utilities for rerendering an existing Reels Editor work directory."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress

from reels_editor import edl, export, render
from reels_editor.config import AppConfig, load_config, merged_style
from reels_editor.storyteller import StorylineResult
from reels_editor.style import StylePreset, load_style

app = typer.Typer(help="창업가 인터뷰 릴스 재렌더 도구")
console = Console()
DEFAULT_STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"
MAX_PARALLEL_RENDERS = 2


@app.callback()
def main() -> None:
    """Existing work-directory rerender commands."""


def preflight(style_path: Path) -> list[str]:
    problems: list[str] = []
    for binname, hint in (("ffmpeg", "brew install ffmpeg"),
                          ("ffprobe", "brew install ffmpeg")):
        if not shutil.which(binname):
            problems.append(f"{binname} 없음 — {hint}")
    try:
        load_style(style_path)
    except (FileNotFoundError, KeyError) as exc:
        problems.append(f"스타일 로드 실패: {exc}")
    return problems


def _fail_if_problems(problems: list[str]) -> None:
    if problems:
        for problem in problems:
            console.print(f"[red]✗[/] {problem}")
        raise typer.Exit(1)


def write_manifest(work: Path, cfg: AppConfig, outputs: list[dict]) -> Path:
    doc = {
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "provider": cfg.provider,
        "model": cfg.model,
        "n_storylines": cfg.n_storylines,
        "style": cfg.style,
        "outputs": outputs,
    }
    path = work / "manifest.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _storyline_outputs(work: Path, index: int, segments: dict, doc: dict,
                       style: StylePreset, speed: float) -> Path:
    story_dir = work / f"s{index + 1}"
    export.write_outputs(story_dir, doc, segments)
    ordered = edl.ordered_segments(doc, segments)
    groups = render.group_captions([
        [start, end, render.apply_text_fixes(text, render.DEFAULT_TEXT_FIXES)]
        for start, end, text in render.timeline_items(ordered, speed)
    ])
    export.write_srt(groups, story_dir / "reel.srt")
    cuts_dir = story_dir / "cuts"
    if cuts_dir.is_dir():
        for old in cuts_dir.glob("*.mp4"):
            old.unlink()
    export.export_cuts(Path(segments["video_path"]), doc, segments, cuts_dir, speed)
    return story_dir


def render_combos(video: Path, segments: dict,
                  storylines: list[StorylineResult],
                  combos: list[tuple[int, int]], style: StylePreset,
                  work: Path, speed: float,
                  progress: Progress | None = None) -> list[dict]:
    """Analyze each storyline once and reuse its crop/caption assets across variants."""
    docs = {result.index: result.doc for result in storylines if result.doc is not None}
    by_story: dict[int, list[int]] = {}
    for storyline_index, title_index in combos:
        by_story.setdefault(storyline_index, []).append(title_index)
    outputs: list[dict] = []

    def one_storyline(storyline_index: int) -> list[dict]:
        doc = docs[storyline_index]
        story_dir = _storyline_outputs(
            work, storyline_index, segments, doc, style, speed,
        )
        task_id = (
            progress.add_task(f"s{storyline_index + 1} 렌더 준비", total=1.0)
            if progress else None
        )
        callback = (
            (lambda fraction: progress.update(task_id, completed=fraction))
            if progress else None
        )
        try:
            assets = render.render_base_and_assets(
                video, segments, doc, style, story_dir / ".render", speed,
                progress_cb=callback,
            )
        except (RuntimeError, ValueError) as exc:
            return [
                {
                    "storyline": storyline_index + 1,
                    "title_index": title_index + 1,
                    "title": doc["title_candidates"][title_index]["text"],
                    "file": None,
                    "error": str(exc),
                }
                for title_index in by_story[storyline_index]
            ]
        rows: list[dict] = []
        for title_index in by_story[storyline_index]:
            title = doc["title_candidates"][title_index]
            output = story_dir / f"reel-t{title_index + 1}.mp4"
            try:
                render.render_with_title(
                    assets,
                    title["text"],
                    title.get("keyword", ""),
                    style,
                    output,
                    speaker_text=render.speaker_label(doc),
                )
                rows.append({
                    "storyline": storyline_index + 1,
                    "title_index": title_index + 1,
                    "title": title["text"],
                    "file": str(output.relative_to(work)),
                    "error": None,
                })
            except RuntimeError as exc:
                rows.append({
                    "storyline": storyline_index + 1,
                    "title_index": title_index + 1,
                    "title": title["text"],
                    "file": None,
                    "error": str(exc),
                })
        if progress and task_id is not None:
            progress.update(task_id, completed=1.0)
        return rows

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS) as executor:
        for rows in executor.map(one_storyline, sorted(by_story)):
            outputs.extend(rows)
    return outputs


@app.command("render")
def render_cmd(workdir: Path,
               speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
               style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
               title: int = typer.Option(1, help="타이틀 번호(1-기반)")) -> None:
    """수동 수정한 edl.json과 segments.json으로 영상을 재렌더한다."""
    edl_path, segments_path = workdir / "edl.json", workdir / "segments.json"
    if not edl_path.is_file() or not segments_path.is_file():
        console.print(f"[red]✗[/] {workdir}에 edl.json/segments.json이 없습니다.")
        raise typer.Exit(1)
    _fail_if_problems(preflight(style))
    cfg = load_config()
    preset = merged_style(load_style(style), cfg.style)
    selected_speed = speed if speed is not None else preset.speed
    edl_doc = json.loads(edl_path.read_text(encoding="utf-8"))
    segments = json.loads(segments_path.read_text(encoding="utf-8"))
    errors = edl.validate_edl(edl_doc, segments)
    if errors:
        console.print("[red]✗ EDL 검증 실패:[/]\n" + "\n".join(errors))
        raise typer.Exit(1)
    video = Path(segments["video_path"])
    assets = render.render_base_and_assets(
        video, segments, edl_doc, preset, workdir / ".render", selected_speed,
    )
    selected_title = edl_doc["title_candidates"][title - 1]
    output = workdir / f"reel-t{title}.mp4"
    render.render_with_title(
        assets,
        selected_title["text"],
        selected_title.get("keyword", ""),
        preset,
        output,
        speaker_text=render.speaker_label(edl_doc),
    )
    console.print(f"[green]✅ 완료:[/] {output}")


if __name__ == "__main__":
    app()
