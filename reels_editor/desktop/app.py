from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from reels_editor.config import AppConfig, load_config
from reels_editor.jobs import JobService, JobStore
from reels_editor.storyteller import build_prompt

from .dialogs import FakeDialogProvider, MutableDialogProvider, WebviewDialogProvider
from .server import UvicornThread, create_app
from .tools import inject_tool_paths


APP_NAME = "Reels Editor"
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "reels-editor"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def default_static_dir() -> Path:
    root = resource_root()
    packaged = root / "reels_editor" / "desktop" / "ui"
    return packaged if packaged.exists() else root / "ui"


def default_media_dir() -> Path:
    root = resource_root() / "media"
    if root.exists():
        return root
    user_dir = APP_SUPPORT_DIR / "media"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def load_desktop_config() -> AppConfig:
    try:
        cfg = load_config()
    except Exception:
        return AppConfig(provider="codex-cli", n_storylines=3)
    return AppConfig(
        provider="codex-cli",
        model=cfg.model if cfg.provider == "codex-cli" else "",
        n_storylines=3,
        voice_isolation=cfg.voice_isolation,
        style=dict(cfg.style),
    )


def _get_json(url: str, token: str | None = None) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urlopen(Request(url, headers=headers), timeout=3) as response:
        return json.loads(response.read().decode())


def _websocket_smoke(base_url: str, token: str) -> dict[str, object]:
    from websockets.sync.client import connect

    ws_url = base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    with connect(f"{ws_url}/api/events?after=-1&token={token}", open_timeout=3, close_timeout=1) as websocket:
        websocket.ping()
    return {"ok": True}


def _prompt_smoke() -> dict[str, object]:
    prompt = build_prompt(
        {"segments": [{"id": "seg-1", "text": "대표가 실행 원칙을 설명합니다."}]},
        30,
        feedback=None,
        angle="정면승부형",
    )
    return {
        "ok": "seg-1" in prompt and "정면승부형" in prompt,
        "chars": len(prompt),
    }


def smoke_payload(base_url: str, *, session_token: str, service: JobService) -> dict[str, object]:
    service.deps.load_style(service.style_path)
    return {
        "base_url": base_url,
        "health": _get_json(f"{base_url}/api/health"),
        "tools": _get_json(f"{base_url}/api/tools", session_token),
        "snapshot": _get_json(f"{base_url}/api/snapshot", session_token),
        "media": _get_json(f"{base_url}/api/media", session_token),
        "websocket": _websocket_smoke(base_url, session_token),
        "prompt": _prompt_smoke(),
        "engine": {
            "style_loaded": True,
            "provider": service.config.provider,
            "model": service.config.model,
        },
    }


def build_desktop_app(
    *,
    static_dir: Path,
    media_dir: Path,
    dialog_provider: MutableDialogProvider,
    session_token: str | None = None,
):
    store = JobStore(APP_SUPPORT_DIR / "jobs")
    store.recover_interrupted()
    service = JobService(store=store, config=load_desktop_config())
    service.deps.load_style(service.style_path)
    app = create_app(
        static_dir=static_dir,
        media_dir=media_dir,
        dialog_provider=dialog_provider,
        job_service=service,
        session_token=session_token,
    )
    return app, service


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Reels Editor macOS desktop app.")
    parser.add_argument("--static-dir", type=Path, default=default_static_dir())
    parser.add_argument("--media-dir", type=Path, default=default_media_dir())
    parser.add_argument("--smoke-exit-after", type=float, default=0)
    parser.add_argument("--smoke-status", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    inject_tool_paths()
    dialog_provider = MutableDialogProvider(FakeDialogProvider())
    session_token = secrets.token_urlsafe(32)
    app, service = build_desktop_app(
        static_dir=args.static_dir,
        media_dir=args.media_dir,
        dialog_provider=dialog_provider,
        session_token=session_token,
    )
    server = UvicornThread(app)
    base_url = server.start()

    import webview

    window_url = f"{base_url}/#token={session_token}"
    window = webview.create_window(APP_NAME, window_url, width=1360, height=840, min_size=(1040, 720))
    dialog_provider.set_provider(WebviewDialogProvider(window))

    def on_started() -> None:
        try:
            if args.smoke_status:
                payload = smoke_payload(base_url, session_token=session_token, service=service)
                args.smoke_status.parent.mkdir(parents=True, exist_ok=True)
                args.smoke_status.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        finally:
            if args.smoke_exit_after > 0:

                def close_later() -> None:
                    time.sleep(args.smoke_exit_after)
                    window.destroy()

                threading.Thread(target=close_later, daemon=True).start()

    try:
        webview.start(on_started, debug=bool(os.environ.get("REELS_DESKTOP_DEBUG")))
    finally:
        service.shutdown()
        server.stop()


if __name__ == "__main__":
    main()
