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
        raise ValueError("The selected Google Drive path is not a folder.")
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
        raise ValueError("The export folder is outside the selected path.")
    if target.exists() and not target.is_dir():
        raise ValueError("The export path is not a folder.")
    return target
