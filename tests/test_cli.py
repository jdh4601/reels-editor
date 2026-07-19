import json
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from typer.testing import CliRunner

from reels_editor import cli, gate
from reels_editor.config import AppConfig, load_config, resolve_api_key
from reels_editor.storyteller import StorylineResult

runner = CliRunner()
STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def _fake_doc(idx: int) -> dict:
    """cuts는 conftest의 segments 픽스처(t1/t2)를 참조하는 2-타이틀 EDL."""
    return {
        "story": {"five_lines": {"situation": "s", "desire": "d", "conflict": "c",
                                 "change": "ch", "result": "r"}, "lens": "lens"},
        "title_candidates": [{"text": f"타이틀{idx}-1", "keyword": ""},
                             {"text": f"타이틀{idx}-2", "keyword": ""}],
        "subtitle_keywords": [],
        "cuts": [{"beat": "훅", "seg_ids": ["t1"], "broll_marker": None},
                 {"beat": "라스트 답", "seg_ids": ["t2"], "broll_marker": None}],
    }


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def test_preflight_reports_missing_project() -> None:
    problems = cli.preflight("존재하지않는프로젝트", STYLE)
    assert any("CapCut" in p for p in problems)


def test_preflight_ok_without_project() -> None:
    # 이 머신에는 ffmpeg/Pretendard가 있으므로 project 없이는 통과 (claude 바이너리는
    # preflight()가 아니라 _preflight_provider()에서 provider별로 검사한다)
    assert cli.preflight(None, STYLE) == []


def test_preflight_provider_requires_matching_cli_binary(monkeypatch) -> None:
    real_which = cli.shutil.which

    def fake_which(name: str):
        return None if name == "claude" else real_which(name)

    monkeypatch.setattr(cli.shutil, "which", fake_which)
    problems = cli._preflight_provider(AppConfig(provider="claude-cli"))
    assert any("claude" in p for p in problems)
    assert cli._preflight_provider(AppConfig(provider="openai")) == []

    def fake_codex_which(name: str):
        return None if name == "codex" else real_which(name)

    monkeypatch.setattr(cli.shutil, "which", fake_codex_which)
    problems = cli._preflight_provider(AppConfig(provider="codex-cli"))
    assert any("codex" in p for p in problems)


def test_make_fails_fast_on_missing_project() -> None:
    result = runner.invoke(cli.app, ["make", "존재하지않는프로젝트"])
    assert result.exit_code == 1
    assert "CapCut" in result.output


def test_help_commands_exit_zero() -> None:
    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["make", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["render", "--help"]).exit_code == 0


# ---------------------------------------------------------------------------
# render (재렌더) — base+title 자산 배선만 검증, 실제 ffmpeg는 호출하지 않는다
# ---------------------------------------------------------------------------

def test_render_command_rerenders_workdir(tmp_path: Path, segments: dict,
                                          edl_doc: dict, monkeypatch) -> None:
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    calls: dict = {}

    class FakeAssets:
        pass

    def fake_base(video_path, segs, doc, style, work_dir, speed, progress_cb=None):
        calls["base"] = (video_path, work_dir, speed)
        return FakeAssets()

    def fake_with_title(assets, title_text, keyword, style, out_path):
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


def test_render_command_respects_title_option(tmp_path: Path, segments: dict,
                                              monkeypatch) -> None:
    doc = _fake_doc(0)
    (tmp_path / "edl.json").write_text(json.dumps(doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    calls: dict = {}

    class FakeAssets:
        pass

    monkeypatch.setattr(cli.render, "render_base_and_assets",
                        lambda *a, **kw: FakeAssets())

    def fake_with_title(assets, title_text, keyword, style, out_path):
        calls["title"] = title_text
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_with_title", fake_with_title)
    result = runner.invoke(cli.app, ["render", str(tmp_path), "--title", "2"])
    assert result.exit_code == 0, result.output
    assert calls["title"] == doc["title_candidates"][1]["text"]
    assert (tmp_path / "reel-t2.mp4").exists()


# ---------------------------------------------------------------------------
# apply_gate_settings — 타입 변환·저장·api_key 분리
# ---------------------------------------------------------------------------

def test_apply_gate_settings_types_and_persists(tmp_path) -> None:
    cfgp, credp = tmp_path / "c.yaml", tmp_path / "cred.yaml"
    cfg = cli.apply_gate_settings(
        {"provider": "kimi", "n_storylines": "2", "sub_size": "52",
         "sub_y_frac": "0.9", "api_key": "sk-new-key-abcd"},
        AppConfig(), cfgp, credp)
    assert cfg.provider == "kimi" and cfg.n_storylines == 2
    assert cfg.style["sub_size"] == 52 and cfg.style["sub_y_frac"] == 0.9
    assert load_config(cfgp) == cfg                      # 저장됨
    assert resolve_api_key("kimi", credp) == "sk-new-key-abcd"


def test_apply_gate_settings_without_api_key_skips_credential_write(tmp_path) -> None:
    cfgp, credp = tmp_path / "c.yaml", tmp_path / "cred.yaml"
    cli.apply_gate_settings({"provider": "openai"}, AppConfig(), cfgp, credp)
    assert not credp.exists()


def test_apply_gate_settings_never_returns_api_key_on_config(tmp_path) -> None:
    cfgp, credp = tmp_path / "c.yaml", tmp_path / "cred.yaml"
    cfg = cli.apply_gate_settings({"api_key": "sk-secret-value"}, AppConfig(),
                                  cfgp, credp)
    assert "api_key" not in cfg.style
    assert not hasattr(cfg, "api_key")
    assert "sk-secret-value" not in cfgp.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# write_manifest — api_key 절대 미포함
# ---------------------------------------------------------------------------

def test_write_manifest_excludes_secrets(tmp_path) -> None:
    p = cli.write_manifest(tmp_path, AppConfig(provider="openai"),
                           [{"storyline": 1, "title_index": 1, "title": "티",
                             "file": "s1/reel-t1.mp4", "error": None}])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["outputs"][0]["file"] == "s1/reel-t1.mp4"
    assert "api_key" not in json.dumps(data)


# ---------------------------------------------------------------------------
# render_combos — base는 스토리라인당 1회(병렬), 타이틀은 조합별 재사용
# ---------------------------------------------------------------------------

def test_render_combos_builds_base_once_and_reuses_for_each_title(
        tmp_path: Path, segments: dict, style_preset, monkeypatch) -> None:
    storylines = [StorylineResult(0, "angle", _fake_doc(0))]
    base_calls: list = []
    title_calls: list = []

    class FakeAssets:
        pass

    def fake_base(video, segs, doc, style, work_dir, speed, progress_cb=None):
        base_calls.append(work_dir)
        return FakeAssets()

    def fake_with_title(assets, title_text, keyword, style, out_path):
        title_calls.append((title_text, out_path))
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_base_and_assets", fake_base)
    monkeypatch.setattr(cli.render, "render_with_title", fake_with_title)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])

    outputs = cli.render_combos(Path("/tmp/footage.mp4"), segments, storylines,
                                [(0, 0), (0, 1)], style_preset, tmp_path, 1.2)

    assert len(base_calls) == 1
    assert len(title_calls) == 2
    assert sorted(o["file"] for o in outputs) == ["s1/reel-t1.mp4", "s1/reel-t2.mp4"]
    assert all(o["error"] is None for o in outputs)


def test_render_combos_runs_independent_storylines_concurrently(
        tmp_path: Path, segments: dict, style_preset, monkeypatch) -> None:
    storylines = [StorylineResult(0, "a", _fake_doc(0)),
                 StorylineResult(1, "b", _fake_doc(1))]
    entered: list = []
    release = threading.Event()

    class FakeAssets:
        pass

    def fake_base(video, segs, doc, style, work_dir, speed, progress_cb=None):
        entered.append(time.monotonic())
        assert release.wait(timeout=5), "두 번째 base 렌더가 진입하지 못함 — 직렬 실행 의심"
        return FakeAssets()

    monkeypatch.setattr(cli.render, "render_base_and_assets", fake_base)
    monkeypatch.setattr(cli.render, "render_with_title",
                        lambda assets, t, k, style, out: Path(out).write_bytes(b"") or out)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])

    result: dict = {}

    def run() -> None:
        result["outputs"] = cli.render_combos(
            Path("/tmp/footage.mp4"), segments, storylines,
            [(0, 0), (1, 0)], style_preset, tmp_path, 1.2)

    th = threading.Thread(target=run)
    th.start()
    deadline = time.monotonic() + 3
    while len(entered) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(entered) == 2, "두 storyline의 base 렌더가 동시에 진입하지 않음(직렬 실행)"
    release.set()
    th.join(timeout=5)
    assert not th.is_alive()
    assert len(result["outputs"]) == 2


def test_render_combos_base_failure_marks_all_its_titles(
        tmp_path: Path, segments: dict, style_preset, monkeypatch) -> None:
    storylines = [StorylineResult(0, "a", _fake_doc(0))]

    def fake_base(*a, **kw):
        raise RuntimeError("ffmpeg 실패: 가짜 오류")

    monkeypatch.setattr(cli.render, "render_base_and_assets", fake_base)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])

    outputs = cli.render_combos(Path("/tmp/footage.mp4"), segments, storylines,
                                [(0, 0), (0, 1)], style_preset, tmp_path, 1.2)
    assert len(outputs) == 2
    assert all(o["file"] is None and o["error"] for o in outputs)


def test_render_combos_marks_only_failed_title(
        tmp_path: Path, segments: dict, style_preset, monkeypatch) -> None:
    storylines = [StorylineResult(0, "a", _fake_doc(0))]

    class FakeAssets:
        pass

    def fake_with_title(assets, title_text, keyword, style, out_path):
        if out_path.name == "reel-t2.mp4":
            raise RuntimeError("타이틀 오버레이 실패")
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_base_and_assets",
                        lambda *a, **kw: FakeAssets())
    monkeypatch.setattr(cli.render, "render_with_title", fake_with_title)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])

    outputs = cli.render_combos(Path("/tmp/footage.mp4"), segments, storylines,
                                [(0, 0), (0, 1)], style_preset, tmp_path, 1.2)
    by_ti = {o["title_index"]: o for o in outputs}
    assert by_ti[1]["error"] is None and by_ti[1]["file"] == "s1/reel-t1.mp4"
    assert by_ti[2]["error"] is not None and by_ti[2]["file"] is None


def test_render_combos_clears_stale_cuts_dir(
        tmp_path: Path, segments: dict, style_preset, monkeypatch) -> None:
    storylines = [StorylineResult(0, "a", _fake_doc(0))]
    stale = tmp_path / "s1" / "cuts" / "999-old.mp4"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    class FakeAssets:
        pass

    monkeypatch.setattr(cli.render, "render_base_and_assets",
                        lambda *a, **kw: FakeAssets())
    monkeypatch.setattr(cli.render, "render_with_title",
                        lambda assets, t, k, style, out: Path(out).write_bytes(b"") or out)
    monkeypatch.setattr(cli.export, "export_cuts", lambda *a, **kw: [])

    cli.render_combos(Path("/tmp/footage.mp4"), segments, storylines, [(0, 0)],
                      style_preset, tmp_path, 1.2)
    assert not stale.exists()


# ---------------------------------------------------------------------------
# _validate_combos — 브라우저 게이트(parse_decision)는 combos를 검증하지 않으므로
# 터미널 경로(gate.parse_combo_selection)와 동일한 규칙을 cli.py 쪽에서 강제한다.
# ---------------------------------------------------------------------------

def test_validate_combos_rejects_unknown_storyline_and_out_of_range_title() -> None:
    storylines = [StorylineResult(0, "a", _fake_doc(0))]
    valid, rejected = cli._validate_combos([(0, 0), (5, 0), (0, 9)], storylines)
    assert valid == [(0, 0)]
    assert any("스토리라인 6" in m for m in rejected)
    assert any("타이틀 10" in m for m in rejected)


def test_validate_combos_skips_failed_storylines() -> None:
    storylines = [StorylineResult(0, "a", None, "생성 실패"),
                 StorylineResult(1, "b", _fake_doc(1))]
    valid, rejected = cli._validate_combos([(0, 0), (1, 0)], storylines)
    assert valid == [(1, 0)]
    assert any("스토리라인 1 없음" in m for m in rejected)


def test_validate_combos_dedupes_preserving_order() -> None:
    storylines = [StorylineResult(0, "a", _fake_doc(0))]
    valid, rejected = cli._validate_combos(
        [(0, 1), (0, 0), (0, 1), (0, 0)], storylines)
    assert valid == [(0, 1), (0, 0)]     # 최초 등장 순서 유지, 중복은 제거
    assert rejected == []


# ---------------------------------------------------------------------------
# preview_fn — /preview 실패 경로가 원본 예외(잠재적 키 포함)를 흘리지 않는지
# ---------------------------------------------------------------------------

def test_preview_fn_never_leaks_raw_exception(tmp_path, style_preset) -> None:
    preview_fn = cli._make_preview_fn(tmp_path, Path("/no/such/video.mp4"),
                                      style_preset, [], {"segments": []})
    try:
        preview_fn({"api_key": "sk-should-not-leak-anywhere", "sub_size": "50"})
        raise AssertionError("preview_fn이 예외를 던지지 않음 — alive가 비어 있어 실패해야 함")
    except RuntimeError as e:
        msg = str(e)
        assert "sk-should-not-leak-anywhere" not in msg
        assert "설정 값을 확인" in msg


def test_preview_leak_masked_end_to_end_through_run_gate_v2(style_preset) -> None:
    """run_gate_v2의 /preview 500 바디가 preview_fn 예외의 원문을 노출하지 않는지
    실제 HTTP 왕복으로 확인 — 알려진 유출 벡터(str(e)[:200])를 닫는 회귀 테스트."""
    preview_fn = cli._make_preview_fn(Path("/tmp"), Path("/no/video.mp4"),
                                      style_preset, [], {"segments": []})
    q: queue.Queue = queue.Queue()
    captured: dict = {}

    def client(url: str) -> None:
        try:
            with urllib.request.urlopen(
                    url + "preview?api_key=sk-leak-check-0000", timeout=5):
                pass
        except urllib.error.HTTPError as e:
            captured["status"] = e.code
            captured["body"] = e.read().decode()
        body = json.dumps({"action": "render", "combos": [[0, 0]], "regen": [],
                           "feedback": "", "settings": {}}).encode()
        req = urllib.request.Request(url + "decision", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)

    def serve() -> None:
        client(q.get())

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    gate.run_gate_v2("<html></html>", preview_fn, open_browser=False,
                     port=0, on_url=q.put)
    t.join(timeout=5)
    assert captured["status"] == 500
    assert "sk-leak-check-0000" not in captured["body"]
    assert "설정 값을 확인" in captured["body"]


# ---------------------------------------------------------------------------
# make() 전체 오케스트레이션 — LLM/게이트/렌더는 모두 모킹, 배선만 검증
# ---------------------------------------------------------------------------

def _wire_common_mocks(monkeypatch, tmp_path: Path, segments: dict):
    monkeypatch.setattr(cli.capcut, "find_project", lambda name: tmp_path)
    monkeypatch.setattr(cli.capcut, "load_project", lambda pdir: {})
    monkeypatch.setattr(cli.capcut, "build_segments", lambda draft: segments)
    monkeypatch.setattr(cli, "build_runner", lambda cfg: (lambda prompt: ""))


def test_make_regenerates_then_renders_and_persists_gate_settings(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    _wire_common_mocks(monkeypatch, tmp_path, segments)

    gen_calls: list = []

    def fake_generate_many(segs, n, duration_s, *, runner, raw_dump_dir,
                           feedback, only_indices):
        gen_calls.append(only_indices)
        indices = only_indices if only_indices is not None else list(range(n))
        return [StorylineResult(i, f"angle{i}", _fake_doc(i)) for i in indices]

    monkeypatch.setattr(cli, "generate_many", fake_generate_many)

    decisions = [
        gate.MultiGateDecision("revise", [], [0], "다시 써줘",
                               {"n_storylines": "2", "sub_size": "55"}),
        gate.MultiGateDecision("render", [(0, 0), (1, 1)], [], "", {}),
    ]
    gate_calls = {"n": 0}

    def fake_gate_terminal(storylines, segs, durations, target_s):
        d = decisions[gate_calls["n"]]
        gate_calls["n"] += 1
        return d

    monkeypatch.setattr(cli.gate, "run_gate_terminal_v2", fake_gate_terminal)

    render_calls: dict = {}

    def fake_render_combos(video, segs, storylines, combos, style, work, speed,
                           progress=None):
        render_calls["combos"] = combos
        render_calls["n_storylines_alive"] = len(storylines)
        return [
            {"storyline": 1, "title_index": 1, "title": "타이틀0-1",
             "file": "s1/reel-t1.mp4", "error": None},
            {"storyline": 2, "title_index": 2, "title": "타이틀1-2",
             "file": "s2/reel-t2.mp4", "error": None},
        ]

    monkeypatch.setattr(cli, "render_combos", fake_render_combos)

    result = runner.invoke(cli.app, ["make", "무엇이든", "--no-ui",
                                    "--storylines", "2",
                                    "--out", str(out_dir),
                                    "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert gen_calls == [None, [0]]           # 1차: 전체 생성, 2차: 0번만 재생성
    assert gate_calls["n"] == 2
    assert render_calls["combos"] == [(0, 0), (1, 1)]
    assert render_calls["n_storylines_alive"] == 2   # regen 대상 아닌 스토리라인도 살아있음

    new_cfg = load_config(config_path)
    assert new_cfg.n_storylines == 2
    assert new_cfg.style["sub_size"] == 55
    assert not (config_path.parent / "credentials.yaml").exists()

    [work] = [p for p in out_dir.iterdir() if p.is_dir()]
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(o["file"] for o in manifest["outputs"]) == \
        ["s1/reel-t1.mp4", "s2/reel-t2.mp4"]
    assert "api_key" not in json.dumps(manifest)
    assert "sk-" not in result.output   # 콘솔 출력에도 키가 새지 않는다


def test_make_exits_nonzero_when_any_output_failed(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    _wire_common_mocks(monkeypatch, tmp_path, segments)
    monkeypatch.setattr(
        cli, "generate_many",
        lambda segs, n, d, *, runner, raw_dump_dir, feedback, only_indices:
            [StorylineResult(0, "angle0", _fake_doc(0))])
    monkeypatch.setattr(
        cli.gate, "run_gate_terminal_v2",
        lambda storylines, segs, durations, target_s:
            gate.MultiGateDecision("render", [(0, 0)], [], "", {}))
    monkeypatch.setattr(
        cli, "render_combos",
        lambda video, segs, storylines, combos, style, work, speed, progress=None:
            [{"storyline": 1, "title_index": 1, "title": "티",
              "file": None, "error": "ffmpeg 실패"}])

    result = runner.invoke(cli.app, ["make", "무엇이든", "--no-ui",
                                    "--storylines", "1",
                                    "--out", str(out_dir),
                                    "--config", str(config_path)])
    assert result.exit_code == 1


def test_make_reopens_gate_on_invalid_settings_without_losing_storylines(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    """게이트 POST의 settings는 config._validate가 ValueError로 거부할 수 있는
    시스템 경계값이다 — out-of-range n_storylines가 와도 raw traceback 없이
    Korean 메시지로 게이트를 다시 열고, 이미 생성된 스토리라인은 재사용해야 한다."""
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    _wire_common_mocks(monkeypatch, tmp_path, segments)

    gen_calls: list = []

    def fake_generate_many(segs, n, duration_s, *, runner, raw_dump_dir,
                           feedback, only_indices):
        gen_calls.append(only_indices)
        indices = only_indices if only_indices is not None else list(range(n))
        return [StorylineResult(i, f"angle{i}", _fake_doc(i)) for i in indices]

    monkeypatch.setattr(cli, "generate_many", fake_generate_many)

    decisions = [
        # n_storylines=99는 config.MAX_STORYLINES(3)를 벗어남 — save_config가
        # ValueError를 던져야 한다.
        gate.MultiGateDecision("render", [(0, 0)], [], "", {"n_storylines": "99"}),
        gate.MultiGateDecision("render", [(0, 0)], [], "", {}),
    ]
    gate_calls = {"n": 0}

    def fake_gate_terminal(storylines, segs, durations, target_s):
        d = decisions[gate_calls["n"]]
        gate_calls["n"] += 1
        return d

    monkeypatch.setattr(cli.gate, "run_gate_terminal_v2", fake_gate_terminal)
    monkeypatch.setattr(
        cli, "render_combos",
        lambda video, segs, storylines, combos, style, work, speed, progress=None:
            [{"storyline": 1, "title_index": 1, "title": "타이틀0-1",
              "file": "s1/reel-t1.mp4", "error": None}])

    result = runner.invoke(cli.app, ["make", "무엇이든", "--no-ui",
                                    "--out", str(out_dir),
                                    "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert result.exception is None                  # ValueError가 흘러나오지 않음
    assert "설정 오류" in result.output
    assert gen_calls == [None, []]                    # 두 번째 라운드는 재생성 없음(작업 보존)
    assert gate_calls["n"] == 2                       # 게이트가 다시 열림

    new_cfg = load_config(config_path)
    assert new_cfg.n_storylines == 3                  # 잘못된 값은 저장되지 않음


def test_make_rejects_invalid_combos_and_dedupes_valid_ones(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    _wire_common_mocks(monkeypatch, tmp_path, segments)
    monkeypatch.setattr(
        cli, "generate_many",
        lambda segs, n, d, *, runner, raw_dump_dir, feedback, only_indices:
            [StorylineResult(0, "angle0", _fake_doc(0))])
    monkeypatch.setattr(
        cli.gate, "run_gate_terminal_v2",
        lambda storylines, segs, durations, target_s:
            gate.MultiGateDecision(
                "render", [(0, 0), (0, 0), (5, 0), (0, 9)], [], "", {}))

    render_calls: dict = {}

    def fake_render_combos(video, segs, storylines, combos, style, work, speed,
                           progress=None):
        render_calls["combos"] = combos
        return [{"storyline": 1, "title_index": 1, "title": "타이틀0-1",
                 "file": "s1/reel-t1.mp4", "error": None}]

    monkeypatch.setattr(cli, "render_combos", fake_render_combos)

    result = runner.invoke(cli.app, ["make", "무엇이든", "--no-ui",
                                    "--storylines", "1",
                                    "--out", str(out_dir),
                                    "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert render_calls["combos"] == [(0, 0)]          # 중복+오류 조합 배제 후 1개만 렌더
    assert "스토리라인 6 없음" in result.output
    assert "타이틀 10 없음" in result.output


def test_make_exits_when_all_combos_invalid(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    _wire_common_mocks(monkeypatch, tmp_path, segments)
    monkeypatch.setattr(
        cli, "generate_many",
        lambda segs, n, d, *, runner, raw_dump_dir, feedback, only_indices:
            [StorylineResult(0, "angle0", _fake_doc(0))])
    monkeypatch.setattr(
        cli.gate, "run_gate_terminal_v2",
        lambda storylines, segs, durations, target_s:
            gate.MultiGateDecision("render", [(5, 0)], [], "", {}))

    render_calls = {"called": False}
    monkeypatch.setattr(
        cli, "render_combos",
        lambda *a, **kw: render_calls.__setitem__("called", True) or [])

    result = runner.invoke(cli.app, ["make", "무엇이든", "--no-ui",
                                    "--storylines", "1",
                                    "--out", str(out_dir),
                                    "--config", str(config_path)])

    assert result.exit_code == 1
    assert "유효한 조합이 없습니다" in result.output
    assert render_calls["called"] is False


def test_make_exits_when_all_storylines_fail_generation(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text("provider: openai\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    _wire_common_mocks(monkeypatch, tmp_path, segments)
    monkeypatch.setattr(
        cli, "generate_many",
        lambda segs, n, d, *, runner, raw_dump_dir, feedback, only_indices:
            [StorylineResult(0, "angle0", None, "LLM 오류")])

    result = runner.invoke(cli.app, ["make", "무엇이든", "--no-ui",
                                    "--storylines", "1",
                                    "--out", str(out_dir),
                                    "--config", str(config_path)])
    assert result.exit_code == 1
    assert "모든 스토리라인 생성 실패" in result.output
