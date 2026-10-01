from __future__ import annotations

import html
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Protocol


NOTES_FOLDER_NAME = "릴스 캡션"

_CREATE_NOTE_SCRIPT = r'''
on run argv
    set noteTitle to item 1 of argv
    set noteBody to item 2 of argv
    set targetFolderName to item 3 of argv
    tell application "Notes"
        if not (exists account "iCloud") then error "iCloud 메모 계정을 찾을 수 없습니다."
        tell account "iCloud"
            if not (exists folder targetFolderName) then
                make new folder with properties {name:targetFolderName}
            end if
            tell folder targetFolderName
                make new note with properties {name:noteTitle, body:noteBody}
            end tell
        end tell
    end tell
    return noteTitle
end run
'''


class NotesError(RuntimeError):
    pass


def caption_body_for_notes(caption: str) -> str:
    """Remove the Instagram heading line before saving the caption to Notes."""
    lines = caption.splitlines()
    if len(lines) < 2:
        return ""
    return "\n".join(lines[1:]).lstrip("\n")


class NotesProvider(Protocol):
    def save_caption(self, title: str, caption: str) -> None:
        ...


@dataclass
class FakeNotesProvider:
    saved_notes: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None

    def save_caption(self, title: str, caption: str) -> None:
        if self.error:
            raise NotesError(self.error)
        self.saved_notes.append((title, caption))


class MacNotesProvider:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self._runner = runner

    def save_caption(self, title: str, caption: str) -> None:
        if not caption.strip():
            raise NotesError("메모에 저장할 캡션이 없습니다.")
        body = "<div>" + html.escape(caption).replace("\n", "<br>") + "</div>"
        try:
            result = self._runner(
                ["osascript", "-e", _CREATE_NOTE_SCRIPT, title.strip(), body, NOTES_FOLDER_NAME],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotesError("Mac 메모 앱을 실행하지 못했습니다.") from exc
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout or "").strip()
        if "-1743" in detail or "not authorized" in detail.lower():
            raise NotesError("시스템 설정에서 Reels Editor의 메모 자동화 권한을 허용하세요.")
        raise NotesError(detail or "Mac 메모 저장에 실패했습니다.")
