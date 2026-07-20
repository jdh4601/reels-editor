from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class DialogProvider(Protocol):
    def choose_folder(self) -> str | None:
        ...

    def choose_save_file(self, suggested_name: str) -> str | None:
        ...


@dataclass
class FakeDialogProvider:
    folder: str = "/tmp/reels-editor/input"
    save_file: str = "/tmp/reels-editor/export.mp4"

    def choose_folder(self) -> str:
        return self.folder

    def choose_save_file(self, suggested_name: str) -> str:
        path = Path(self.save_file)
        return str(path.with_name(suggested_name)) if suggested_name else str(path)


class MutableDialogProvider:
    def __init__(self, provider: DialogProvider):
        self.provider = provider

    def set_provider(self, provider: DialogProvider) -> None:
        self.provider = provider

    def choose_folder(self) -> str | None:
        return self.provider.choose_folder()

    def choose_save_file(self, suggested_name: str) -> str | None:
        return self.provider.choose_save_file(suggested_name)


class WebviewDialogProvider:
    def __init__(self, window):
        self.window = window

    def choose_folder(self) -> str | None:
        import webview

        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def choose_save_file(self, suggested_name: str) -> str | None:
        import webview

        result = self.window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested_name or "reel.mp4",
            file_types=("MP4 video (*.mp4)",),
        )
        if isinstance(result, tuple):
            return result[0] if result else None
        return result
