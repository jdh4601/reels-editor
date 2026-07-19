"""reels-editor CLI — make(다중 스토리라인 파이프라인) / render(재렌더)."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from reels_editor import capcut, edl, export, gate, gate_html, preview, render
from reels_editor.config import (
    STYLE_OVERRIDE_KEYS, AppConfig, load_config, mask_key, merged_style,
    resolve_api_key, save_config, save_credential,
)
from reels_editor.llm import build_runner
from reels_editor.storyteller import StorylineResult, generate_many
from reels_editor.style import StylePreset, load_style

app = typer.Typer(help="창업가 인터뷰 → 30초 스토리텔링 릴스")
console = Console()
DEFAULT_STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"
MAX_PARALLEL_RENDERS = 2

_INT_KEYS = {"n_storylines", "sub_size", "title_size", "sub_box_alpha"}
_FLOAT_KEYS = {"sub_y_frac", "speed"}


def preflight(project: str | None, style_path: Path) -> list[str]:
    problems: list[str] = []
    for binname, hint in (("ffmpeg", "brew install ffmpeg"),
                          ("ffprobe", "brew install ffmpeg")):
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


def _preflight_provider(cfg: AppConfig) -> list[str]:
    """CLI 프로바이더는 대응 로컬 바이너리가 필요하다."""
    if cfg.provider == "claude-cli" and not shutil.which("claude"):
        return ["claude 없음 — Claude Code CLI 설치 또는 게이트에서 프로바이더 변경"]
    if cfg.provider == "codex-cli" and not shutil.which("codex"):
        return ["codex 없음 — OpenAI Codex CLI 설치 또는 게이트에서 프로바이더 변경"]
    return []


def _fail_if_problems(problems: list[str]) -> None:
    if problems:
        for p in problems:
            console.print(f"[red]✗[/] {p}")
        raise typer.Exit(1)


def apply_gate_settings(settings: dict, cfg: AppConfig,
                        config_path: Path | None = None,
                        creds_path: Path | None = None) -> AppConfig:
    """게이트가 보낸 문자열 설정을 타입 변환해 저장. api_key는 credentials로 분리하고
    반환되는 AppConfig/저장되는 config.yaml에는 절대 포함하지 않는다."""
    s = dict(settings)
    api_key = s.pop("api_key", None)
    style = dict(cfg.style)
    top: dict = {}
    for k, v in s.items():
        if k in _INT_KEYS:
            v = int(v)
        elif k in _FLOAT_KEYS:
            v = float(v)
        if k in STYLE_OVERRIDE_KEYS:
            style[k] = v
        elif k in ("provider", "model", "base_url", "n_storylines"):
            top[k] = v
    new = dataclasses.replace(cfg, style=style, **top)
    save_config(new, config_path)
    if api_key:
        save_credential(new.provider, api_key, creds_path)
    return new


def write_manifest(work: Path, cfg: AppConfig, outputs: list[dict]) -> Path:
    """outputs/cfg를 manifest.json으로 기록. cfg(AppConfig)에는 api_key 필드 자체가
    없으므로 여기서 직렬화해도 키가 섞여 들어올 여지가 없다."""
    doc = {"created": dt.datetime.now().isoformat(timespec="seconds"),
           "provider": cfg.provider, "model": cfg.model,
           "n_storylines": cfg.n_storylines, "style": cfg.style,
           "outputs": outputs}
    p = work / "manifest.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _storyline_outputs(work: Path, si: int, segments: dict, doc: dict,
                       style: StylePreset, speed: float) -> Path:
    """스토리라인 폴더에 수정용 재료(edl/segments/srt/cuts) 기록."""
    sdir = work / f"s{si + 1}"
    export.write_outputs(sdir, doc, segments)
    ordered = edl.ordered_segments(doc, segments)
    groups = render.group_captions([
        [a, b, render.apply_text_fixes(t, render.DEFAULT_TEXT_FIXES)]
        for a, b, t in render.timeline_items(ordered, speed)])
    export.write_srt(groups, sdir / "reel.srt")
    cuts_dir = sdir / "cuts"
    if cuts_dir.is_dir():
        for old in cuts_dir.glob("*.mp4"):
            old.unlink()
    export.export_cuts(Path(segments["video_path"]), doc, segments, cuts_dir, speed)
    return sdir


def render_combos(video: Path, segments: dict,
                  storylines: list[StorylineResult],
                  combos: list[tuple[int, int]], style: StylePreset,
                  work: Path, speed: float,
                  progress: Progress | None = None) -> list[dict]:
    """base는 스토리라인당 1회(병렬 2), 타이틀 오버레이는 조합별로 재사용."""
    docs = {r.index: r.doc for r in storylines if r.doc is not None}
    by_story: dict[int, list[int]] = {}
    for si, ti in combos:
        by_story.setdefault(si, []).append(ti)
    outputs: list[dict] = []

    def one_storyline(si: int) -> list[dict]:
        doc = docs[si]
        sdir = _storyline_outputs(work, si, segments, doc, style, speed)
        task_id = (progress.add_task(f"s{si + 1} base 렌더", total=1.0)
                   if progress else None)
        cb = ((lambda f: progress.update(task_id, completed=f))
              if progress else None)
        try:
            assets = render.render_base_and_assets(
                video, segments, doc, style, sdir / ".render", speed,
                progress_cb=cb)
        except (RuntimeError, ValueError) as e:
            return [{"storyline": si + 1, "title_index": ti + 1,
                     "title": doc["title_candidates"][ti]["text"],
                     "file": None, "error": str(e)} for ti in by_story[si]]
        rows: list[dict] = []
        for ti in by_story[si]:
            t = doc["title_candidates"][ti]
            out = sdir / f"reel-t{ti + 1}.mp4"
            try:
                render.render_with_title(assets, t["text"],
                                         t.get("keyword", ""), style, out)
                rows.append({"storyline": si + 1, "title_index": ti + 1,
                             "title": t["text"],
                             "file": str(out.relative_to(work)), "error": None})
            except RuntimeError as e:
                rows.append({"storyline": si + 1, "title_index": ti + 1,
                             "title": t["text"], "file": None, "error": str(e)})
        if progress and task_id is not None:
            progress.update(task_id, completed=1.0)
        return rows

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS) as ex:
        for rows in ex.map(one_storyline, sorted(by_story)):
            outputs.extend(rows)
    return outputs


def _validate_combos(combos: list[tuple[int, int]],
                     storylines: list[StorylineResult]
                     ) -> tuple[list[tuple[int, int]], list[str]]:
    """게이트 POST가 보낸 combos는 신뢰하지 않는다 — 터미널 경로(gate.parse_combo_selection)와
    동일한 규칙으로 검증해, 실패한 스토리라인이나 범위 밖 타이틀 인덱스가 render_combos의
    KeyError/IndexError로 이어지지 않게 걸러낸다. 중복 조합은 최초 등장 순서만 남긴다."""
    by_index = {r.index: r for r in storylines if r.doc is not None}
    valid: list[tuple[int, int]] = []
    rejected: list[str] = []
    seen: set[tuple[int, int]] = set()
    for si, ti in combos:
        if (si, ti) in seen:
            continue
        if si not in by_index:
            rejected.append(f"스토리라인 {si + 1} 없음")
            continue
        titles = by_index[si].doc["title_candidates"]
        if not 0 <= ti < len(titles):
            rejected.append(f"타이틀 {ti + 1} 없음 (스토리라인 {si + 1})")
            continue
        seen.add((si, ti))
        valid.append((si, ti))
    return valid, rejected


def _report_outputs(work: Path, cfg: AppConfig, outputs: list[dict]) -> None:
    """manifest 기록 + 콘솔 리포트. 실패한 출력이 하나라도 있으면 typer.Exit(1)."""
    write_manifest(work, cfg, outputs)
    for o in outputs:
        mark = "[green]✅[/]" if not o["error"] else f"[red]✗ {o['error']}[/]"
        target = o["file"] or f"s{o['storyline']}/reel-t{o['title_index']}.mp4"
        console.print(f"{mark} {target} — {o['title']}")
    console.print(f"📄 manifest: {work}/manifest.json")
    if any(o["error"] for o in outputs):
        raise typer.Exit(1)


def _key_status(cfg: AppConfig) -> dict[str, str]:
    status = {}
    for p in ("openai", "kimi", "custom"):
        key = resolve_api_key(p)
        status[p] = f"✓ {mask_key(key)}" if key else "✗ 없음"
    return status


def _make_preview_fn(work: Path, video: Path, preset: StylePreset,
                     alive: list[StorylineResult], segments: dict):
    """게이트 설정 패널의 /preview 콜백. 실패 시 원본 예외 메시지를 절대 그대로
    상위(HTTP 500 바디)로 흘리지 않는다 — ffmpeg stderr나 반사된 쿼리 파라미터에
    API 키 등 민감정보가 섞여 있을 수 있기 때문이다."""

    def preview_fn(params: dict) -> bytes:
        safe_params = {k: v for k, v in params.items() if k != "api_key"}
        try:
            p_style = merged_style(preset, {
                k: (int(v) if k in _INT_KEYS else
                    float(v) if k in _FLOAT_KEYS else v)
                for k, v in safe_params.items() if k in STYLE_OVERRIDE_KEYS})
            first = next(r for r in alive if r.doc is not None)
            t0 = first.doc["title_candidates"][0]
            sub = first.doc["cuts"][0]
            idx = {s["id"]: s for s in segments["segments"]}
            sub_text = " ".join(idx[sid]["text"]
                                for sid in sub["seg_ids"] if sid in idx)[:20]
            frame = preview.extract_frame(
                video,
                idx[sub["seg_ids"][0]]["source_start_us"] / capcut.US,
                work / ".thumbs" / "preview_frame.png")
            return preview.compose_preview(
                frame, t0["text"], t0.get("keyword", ""), sub_text,
                first.doc.get("subtitle_keywords", []), p_style)
        except Exception as e:  # noqa: BLE001 — 안전한 메시지로만 재포장해 전파
            raise RuntimeError("프리뷰 생성 실패 — 설정 값을 확인하세요.") from e

    return preview_fn


def _review_until_render(cfg: AppConfig, segments: dict, duration: int, work: Path,
                         video: Path, preset: StylePreset, spd: float,
                         speed_opt: float | None, no_ui: bool, style: Path,
                         config: Path | None, creds_path: Path | None
                         ) -> tuple["gate.MultiGateDecision", AppConfig, StylePreset,
                                    float, list[StorylineResult]]:
    """대본 생성 → 게이트 표시를 action == "render"가 나올 때까지 반복.

    게이트 POST의 settings는 config._validate에서 ValueError로 거부될 수 있는
    시스템 경계값이다 — 이미 LLM 생성을 기다린 뒤이므로, 잘못된 값 하나 때문에
    그 작업을 버리고 abort하는 대신 재생성 없이(todo=[]) 게이트를 다시 열어
    사용자가 값을 고쳐 재제출하게 한다.
    """
    results: dict[int, StorylineResult] = {}
    feedback: str | None = None
    todo: list[int] | None = None      # None = 전체 생성
    while True:
        runner = build_runner(cfg)
        with console.status(f"🧠 대본 생성 중 ({cfg.provider}) — "
                            f"스토리라인 {cfg.n_storylines}개 병렬…"):
            fresh = generate_many(segments, cfg.n_storylines, duration,
                                  runner=runner, raw_dump_dir=work,
                                  feedback=feedback, only_indices=todo)
        for r in fresh:
            results[r.index] = r
            mark = "[green]✓[/]" if r.doc else f"[red]✗ {r.error}[/]"
            console.print(f"  스토리라인 {r.index + 1} ({r.angle_name}) {mark}")
        alive = [results[i] for i in sorted(results)]
        if all(r.doc is None for r in alive):
            console.print("[red]✗ 모든 스토리라인 생성 실패[/] — "
                          f"원문 응답: {work}/llm_raw_s*.txt")
            raise typer.Exit(1)
        durations = {r.index: edl.estimate_duration_s(r.doc, segments, spd)
                     for r in alive if r.doc is not None}
        if no_ui:
            decision = gate.run_gate_terminal_v2(alive, segments, durations,
                                                 duration)
        else:
            thumbs = {r.index: gate.extract_thumbs(video, r.doc, segments,
                                                   work / f".thumbs/s{r.index + 1}")
                      for r in alive if r.doc is not None}
            html = gate_html.build_gate_html(alive, segments, thumbs, durations,
                                             duration, cfg, _key_status(cfg))
            preview_fn = _make_preview_fn(work, video, preset, alive, segments)
            console.print("⏳ 브라우저에서 검토를 완료하세요…")
            decision = gate.run_gate_v2(html, preview_fn)
        if decision.settings:
            try:
                cfg = apply_gate_settings(decision.settings, cfg, config, creds_path)
            except ValueError as e:
                console.print(f"[red]✗ 설정 오류:[/] {e} — 값을 고쳐 다시 제출하세요.")
                feedback, todo = None, []
                continue
            preset = merged_style(load_style(style), cfg.style)
            spd = speed_opt if speed_opt is not None else preset.speed
        if decision.action == "render":
            return decision, cfg, preset, spd, alive
        feedback = decision.feedback or None
        todo = decision.regen


@app.command()
def make(project: str,
         speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
         duration: int = typer.Option(30, help="목표 길이(초)"),
         style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
         storylines: int = typer.Option(None, help="스토리라인 개수 (기본: 설정)"),
         no_ui: bool = typer.Option(False, "--no-ui", help="터미널 게이트 사용"),
         out: Path = typer.Option(Path("out"), help="산출물 루트"),
         config: Path = typer.Option(
             None, "--config", help="설정 파일 경로 (테스트용 — 미지정 시 사용자 기본 경로)"
         )) -> None:
    """CapCut 프로젝트 → 다중 스토리라인 게이트 → 조합별 릴스."""
    _fail_if_problems(preflight(project, style))
    cfg = load_config(config)
    _fail_if_problems(_preflight_provider(cfg))
    creds_path = (config.parent / "credentials.yaml") if config is not None else None
    if storylines is not None:
        cfg = dataclasses.replace(cfg, n_storylines=storylines)
    preset = merged_style(load_style(style), cfg.style)
    spd = speed if speed is not None else preset.speed
    pdir = capcut.find_project(project)
    segments = capcut.build_segments(capcut.load_project(pdir))
    video = Path(segments["video_path"])
    work = out / f"{pdir.name}-{dt.date.today():%Y%m%d}"
    work.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓[/] 자막 {len(segments['segments'])}개 로드")

    decision, cfg, preset, spd, alive = _review_until_render(
        cfg, segments, duration, work, video, preset, spd, speed,
        no_ui, style, config, creds_path)

    combos, rejected = _validate_combos(decision.combos, alive)
    for msg in rejected:
        console.print(f"[red]✗ 조합 거부:[/] {msg}")
    if not combos:
        console.print("[red]✗ 렌더할 유효한 조합이 없습니다[/]")
        raise typer.Exit(1)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), console=console) as progress:
        outputs = render_combos(video, segments, alive, combos,
                                preset, work, spd, progress)
    _report_outputs(work, cfg, outputs)


@app.command("render")
def render_cmd(workdir: Path,
               speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
               style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
               title: int = typer.Option(1, help="타이틀 번호(1-기반)")) -> None:
    """수동 수정한 s*/edl.json으로 재렌더 (게이트·LLM 없이)."""
    edl_path, seg_path = workdir / "edl.json", workdir / "segments.json"
    if not edl_path.is_file() or not seg_path.is_file():
        console.print(f"[red]✗[/] {workdir}에 edl.json/segments.json이 없습니다.")
        raise typer.Exit(1)
    _fail_if_problems(preflight(None, style))
    cfg = load_config()
    preset = merged_style(load_style(style), cfg.style)
    spd = speed if speed is not None else preset.speed
    edl_doc = json.loads(edl_path.read_text(encoding="utf-8"))
    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    errs = edl.validate_edl(edl_doc, segments)
    if errs:
        console.print("[red]✗ EDL 검증 실패:[/]\n" + "\n".join(errs))
        raise typer.Exit(1)
    video = Path(segments["video_path"])
    assets = render.render_base_and_assets(video, segments, edl_doc, preset,
                                           workdir / ".render", spd)
    t = edl_doc["title_candidates"][title - 1]
    out_path = workdir / f"reel-t{title}.mp4"
    render.render_with_title(assets, t["text"], t.get("keyword", ""), preset,
                             out_path)
    console.print(f"[green]✅ 완료:[/] {out_path}")


if __name__ == "__main__":
    app()
