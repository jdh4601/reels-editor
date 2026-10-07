"""Resolve the episode export folder, including macOS Unicode filenames."""
from pathlib import Path
import unicodedata

EPISODE_FOLDER = "릴스(에피소드)"


def _normalized(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _child(root: Path, name: str) -> Path:
    for path in root.iterdir():
        if _normalized(path.name) == name:
            return path
    return root / name


def episode_export_root(selected: Path) -> Path:
    root = selected.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("선택한 Google Drive 저장 경로가 폴더가 아닙니다.")
    if _normalized(root.name) == EPISODE_FOLDER:
        return root
    if root.name.startswith("GoogleDrive-"):
        for name in ("My Drive", "내 드라이브"):
            child = _child(root, name)
            if child.is_dir():
                root = child.resolve(strict=True)
                break
    target = _child(root, EPISODE_FOLDER)
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("릴스(에피소드) 저장 폴더가 선택 경로 밖에 있습니다.")
    if target.exists() and not target.is_dir():
        raise ValueError("릴스(에피소드) 경로가 폴더가 아닙니다.")
    return target
