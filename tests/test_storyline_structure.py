from __future__ import annotations

import json
from pathlib import Path

from reels_editor.desktop.server import _storyline_snapshot
from reels_editor.jobs import Job, Status, Storyline


def test_storyline_snapshot_returns_complete_role_labeled_sections(tmp_path: Path) -> None:
    hook = "할머니의 사고를 계기로 꼭 해결하겠다고 결심했습니다. " * 4
    ending = "지금이 아니면 늦는다는 생각으로 바로 시작했습니다."
    segments = {
        "segments": [
            {"id": "hook-1", "text": hook},
            {"id": "ending-1", "text": ending},
        ]
    }
    edl = {
        "story": {"five_lines": {}, "lens": "사고에서 시작된 결심"},
        "cuts": [
            {"beat": "훅", "seg_ids": ["hook-1"]},
            {"beat": "라스트 답", "seg_ids": ["ending-1"]},
        ],
    }
    segments_path = tmp_path / "segments.json"
    edl_path = tmp_path / "edl.json"
    segments_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    edl_path.write_text(json.dumps(edl, ensure_ascii=False), encoding="utf-8")
    storyline = Storyline(
        id="s1",
        index=0,
        angle_name="감정선형",
        edl_path=str(edl_path),
        segments_path=str(segments_path),
    )

    snapshot = _storyline_snapshot(Job(id="job-1"), storyline)

    assert len(snapshot["summary"]) > 140
    assert snapshot["summary"] == f"{hook.strip()} {ending}"
    assert snapshot["sections"] == [
        {
            "beat": "훅",
            "role": "첫 3초에 시선을 붙잡는 문장",
            "text": hook.strip(),
        },
        {
            "beat": "라스트 답",
            "role": "영상이 남기는 결론과 메시지",
            "text": ending,
        },
    ]


def test_storyline_snapshot_displays_korean_translations_for_english_source(tmp_path: Path) -> None:
    segments = {
        "transcript_language": "en",
        "segments": [{"id": "hook-1", "text": "Startups are brutally hard."}],
    }
    edl = {
        "subtitle_translations": {"hook-1": "창업은 정말 지독하게 어렵습니다."},
        "cuts": [{"beat": "훅", "seg_ids": ["hook-1"]}],
    }
    segments_path = tmp_path / "segments.json"
    edl_path = tmp_path / "edl.json"
    segments_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    edl_path.write_text(json.dumps(edl, ensure_ascii=False), encoding="utf-8")
    storyline = Storyline(
        id="s1",
        index=0,
        angle_name="정면승부형",
        edl_path=str(edl_path),
        segments_path=str(segments_path),
    )

    snapshot = _storyline_snapshot(Job(id="job-1"), storyline)

    assert snapshot["summary"] == "창업은 정말 지독하게 어렵습니다."
    assert snapshot["sections"][0]["text"] == "창업은 정말 지독하게 어렵습니다."


def test_storyline_snapshot_hides_raw_llm_response_from_user() -> None:
    storyline = Storyline(
        id="s1",
        index=0,
        status=Status.FAILED,
        error="RuntimeError: 대본 생성 3회 실패 — 마지막 응답:\n" + "raw-json " * 1000,
    )

    snapshot = _storyline_snapshot(Job(id="job-1"), storyline)

    assert "JSON 따옴표 형식" in snapshot["error"]
    assert "raw-json" not in snapshot["error"]
    assert snapshot["summary"] == snapshot["error"]
