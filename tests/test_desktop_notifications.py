from __future__ import annotations

import subprocess

from reels_editor.desktop import notifications


def test_macos_notification_uses_native_osascript(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(notifications.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        notifications.subprocess,
        "Popen",
        lambda args, **_kwargs: calls.append(args),
    )

    notifications.show_macos_notification('릴스 "완료"', "후보가 준비되었습니다.")

    assert calls == [[
        "/usr/bin/osascript",
        "-e",
        'display notification "후보가 준비되었습니다." with title "릴스 \\"완료\\""',
    ]]


def test_notification_is_skipped_outside_macos(monkeypatch) -> None:
    monkeypatch.setattr(notifications.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    notifications.show_macos_notification("완료", "준비되었습니다.")
