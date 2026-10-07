"""Local desktop engine with fake external media/AI for the browser regression test."""
from dataclasses import replace
from pathlib import Path
import sys
import time

import uvicorn

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "tests")]
from test_job_service import Calls, _deps
from reels_editor.desktop.server import create_app
from reels_editor.jobs import JobService, JobStore

work = Path(sys.argv[1])
deps = _deps(work, Calls())
original_render = deps.render_base_and_assets


def render(*args, **kwargs):
    deadline = time.monotonic() + 30
    while not (work / "release-render").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Browser test did not release rendering")
        time.sleep(0.02)
    return original_render(*args, **kwargs)


def suggest_titles(**kwargs):
    return [
        "성장하는 회사에서 대표가 놓치는 위험 신호",
        "회사가 커질수록 대표가 외로워지는 이유",
        "성공에 내 자존심을 걸면 안 되는 이유",
        "성공을 붙잡다가 팀을 놓치는 대표들",
        "회사는 마라톤인데 혼자 달리는 대표들",
    ]


service = JobService(store=JobStore(work / "jobs"), deps=replace(deps, render_base_and_assets=render, generate_title_suggestion=suggest_titles))
app = create_app(static_dir=root / "reels_editor/desktop/ui", media_dir=work, job_service=service, session_token="parallel-test", config_path=work / "config.yaml")
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="warning", timeout_graceful_shutdown=1)
