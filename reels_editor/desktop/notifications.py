from __future__ import annotations

import platform


def show_macos_notification(title: str, message: str) -> None:
    """Show a best-effort notification attributed to the Reels Editor app."""
    if platform.system() != "Darwin":
        return

    try:
        notification_class, center_class = _notification_classes()
        notification = notification_class.alloc().init()
        notification.setTitle_(title)
        notification.setInformativeText_(message)
        center_class.defaultUserNotificationCenter().deliverNotification_(notification)
    except (ImportError, OSError, RuntimeError):
        # Notifications are a convenience and must never fail a render job.
        return


def _notification_classes():
    # Sending from the app process makes Notification Center use the bundle's
    # ReelsEditor.icns instead of osascript's generic crossed-tools icon.
    from Foundation import NSUserNotification, NSUserNotificationCenter

    return NSUserNotification, NSUserNotificationCenter
