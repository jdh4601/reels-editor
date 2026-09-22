from __future__ import annotations

from reels_editor.desktop import notifications


def test_macos_notification_is_sent_by_app_process(monkeypatch) -> None:
    delivered: list[object] = []

    class FakeNotification:
        title = ""
        message = ""

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setTitle_(self, value: str) -> None:
            self.title = value

        def setInformativeText_(self, value: str) -> None:
            self.message = value

    class FakeCenter:
        @classmethod
        def defaultUserNotificationCenter(cls):
            return cls()

        def deliverNotification_(self, notification: object) -> None:
            delivered.append(notification)

    monkeypatch.setattr(notifications.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        notifications,
        "_notification_classes",
        lambda: (FakeNotification, FakeCenter),
    )

    notifications.show_macos_notification('릴스 "완료"', "후보가 준비되었습니다.")

    assert len(delivered) == 1
    assert delivered[0].title == '릴스 "완료"'
    assert delivered[0].message == "후보가 준비되었습니다."


def test_notification_is_skipped_outside_macos(monkeypatch) -> None:
    monkeypatch.setattr(notifications.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        notifications,
        "_notification_classes",
        lambda: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    notifications.show_macos_notification("완료", "준비되었습니다.")
