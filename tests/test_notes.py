from __future__ import annotations

import subprocess

import pytest

from reels_editor.desktop.notes import MacNotesProvider, NotesError, caption_body_for_notes


def test_caption_body_for_notes_removes_heading_and_blank_line() -> None:
    caption = "Ep 12. 문제가 희귀할수록 테스트는 더 극단적이어야 한다\n\n첫 문단\n\n두 번째 문단"

    assert caption_body_for_notes(caption) == "첫 문단\n\n두 번째 문단"


def test_caption_body_for_notes_rejects_heading_only_caption() -> None:
    assert caption_body_for_notes("Ep 12. 제목") == ""


def test_mac_notes_provider_passes_escaped_caption_to_icloud_notes() -> None:
    captured: dict[str, object] = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="saved", stderr="")

    MacNotesProvider(runner=runner).save_caption("에피소드3_성장", "A & B\n두 번째 줄")

    command = captured["command"]
    assert isinstance(command, list)
    assert command[0:2] == ["osascript", "-e"]
    assert command[-3] == "에피소드3_성장"
    assert command[-2] == "<div>A &amp; B<br>두 번째 줄</div>"
    assert command[-1] == "릴스 캡션"
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": 20,
        "check": False,
    }


def test_mac_notes_provider_explains_automation_permission_failure() -> None:
    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Not authorized (-1743)")

    with pytest.raises(NotesError, match="자동화 권한"):
        MacNotesProvider(runner=runner).save_caption("제목", "캡션")
