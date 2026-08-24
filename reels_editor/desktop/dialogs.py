from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class DialogProvider(Protocol):
    def choose_folder(self) -> str | None:
        ...

    def choose_save_file(self, suggested_name: str) -> str | None:
        ...

    def show_in_file_manager(self, directory: Path) -> bool:
        ...


@dataclass
class FakeDialogProvider:
    folder: str = "/tmp/reels-editor/input"
    save_file: str = "/tmp/reels-editor/export.mp4"
    opened_directories: list[Path] = field(default_factory=list, init=False)

    def choose_folder(self) -> str:
        return self.folder

    def choose_save_file(self, suggested_name: str) -> str:
        path = Path(self.save_file)
        return str(path.with_name(suggested_name)) if suggested_name else str(path)

    def show_in_file_manager(self, directory: Path) -> bool:
        self.opened_directories.append(directory)
        return True


class MutableDialogProvider:
    def __init__(self, provider: DialogProvider):
        self.provider = provider

    def set_provider(self, provider: DialogProvider) -> None:
        self.provider = provider

    def choose_folder(self) -> str | None:
        return self.provider.choose_folder()

    def choose_save_file(self, suggested_name: str) -> str | None:
        return self.provider.choose_save_file(suggested_name)

    def show_in_file_manager(self, directory: Path) -> bool:
        return self.provider.show_in_file_manager(directory)


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

    def show_in_file_manager(self, directory: Path) -> bool:
        try:
            subprocess.Popen(
                ["open", str(directory.expanduser())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return True
