from pathlib import Path
import unicodedata

import pytest

from reels_editor.drive_paths import EPISODE_FOLDER, episode_export_root


def test_my_drive_resolves_existing_decomposed_korean_folder(tmp_path: Path):
    drive = tmp_path / 'My Drive'
    target = drive / unicodedata.normalize('NFD', EPISODE_FOLDER)
    target.mkdir(parents=True)
    assert episode_export_root(drive) == target
    assert episode_export_root(target) == target
    assert list(drive.iterdir()) == [target]


def test_account_root_uses_my_drive_and_direct_target_is_not_nested(tmp_path: Path):
    account = tmp_path / 'GoogleDrive-example'
    drive = account / 'My Drive'
    drive.mkdir(parents=True)
    target = episode_export_root(account)
    assert target == drive / EPISODE_FOLDER
    assert not target.exists()  # Resolving settings does not create folders.
    target.mkdir()
    assert episode_export_root(target) == target


def test_episode_folder_cannot_redirect_outside_selected_drive(tmp_path: Path):
    drive = tmp_path / 'My Drive'
    outside = tmp_path / 'outside'
    drive.mkdir()
    outside.mkdir()
    (drive / EPISODE_FOLDER).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='선택 경로 밖'):
        episode_export_root(drive)
