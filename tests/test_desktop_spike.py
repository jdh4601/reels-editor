from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reels_editor.desktop.dialogs import FakeDialogProvider
from reels_editor.desktop.app import load_desktop_config
from reels_editor.desktop.server import create_app
from reels_editor.desktop.tools import inject_tool_paths, resolve_tool
from reels_editor import storyteller


def test_tool_resolution_checks_gui_launch_paths_first(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / ".npm-global" / "bin"
    fake_bin.mkdir(parents=True)
    codex = fake_bin / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex.chmod(0o755)

    monkeypatch.setattr("reels_editor.desktop.tools.Path.home", lambda: tmp_path)
    assert resolve_tool("codex") == str(codex)


def test_inject_tool_paths_adds_common_gui_paths(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / ".npm-global" / "bin"
    fake_bin.mkdir(parents=True)
    monkeypatch.setattr("reels_editor.desktop.tools.Path.home", lambda: tmp_path)

    env = {"PATH": "/usr/bin"}
    path = inject_tool_paths(env)

    assert path.split(":")[0] == str(fake_bin)
    assert env["PATH"].endswith("/usr/bin")


def test_desktop_config_forces_codex_cli_provider(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "reels-editor").mkdir()
    (config_dir / "reels-editor" / "config.yaml").write_text(
        "provider: openai\nmodel: gpt-4o\nn_storylines: 1\nstyle:\n  speed: 1.2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

    cfg = load_desktop_config()

    assert cfg.provider == "codex-cli"
    assert cfg.model == ""
    assert cfg.n_storylines == 3
    assert cfg.style == {"speed": 1.2}


def test_desktop_config_preserves_codex_model(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "reels-editor").mkdir()
    (config_dir / "reels-editor" / "config.yaml").write_text(
        "provider: codex-cli\nmodel: gpt-5.6-sol\nn_storylines: 2\nstyle: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

    cfg = load_desktop_config()

    assert cfg.provider == "codex-cli"
    assert cfg.model == "gpt-5.6-sol"
    assert cfg.n_storylines == 3


def test_storyteller_prompt_loads_from_resource_layout(tmp_path: Path, monkeypatch) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "storytelling-30s.md"
    prompt_path.write_text(
        "{angle_block}\n{segments_listing}\n{schema}\n{duration_s}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(storyteller, "PROMPT_PATH", prompt_path)

    prompt = storyteller.build_prompt(
        {"segments": [{"id": "seg-1", "text": "대표가 실행 원칙을 설명합니다."}]},
        30,
        None,
        angle="정면승부형",
    )

    assert "정면승부형" in prompt
    assert "- seg-1: 대표가 실행 원칙을 설명합니다." in prompt
    assert "title_candidates" in prompt


def test_desktop_api_dialog_seam_and_media_listing(tmp_path: Path) -> None:
    static_dir = tmp_path / "ui"
    media_dir = tmp_path / "media"
    static_dir.mkdir()
    media_dir.mkdir()
    (static_dir / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    for index in range(1, 4):
        (media_dir / f"sample-{index}.mp4").write_bytes(b"fake mp4")

    app = create_app(
        static_dir=static_dir,
        media_dir=media_dir,
        dialog_provider=FakeDialogProvider(folder="/chosen", save_file="/exports/out.mp4"),
        session_token="test-token",
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    assert client.get("/api/health").json()["ok"] is True
    assert client.post("/api/dialogs/open-folder", headers=headers).json() == {"path": "/chosen"}
    assert client.post("/api/dialogs/save-file", headers=headers, json={"suggested_name": "custom.mp4"}).json() == {
        "path": "/exports/custom.mp4"
    }
    media = client.get("/api/media", headers=headers).json()["items"]
    assert [item["name"] for item in media] == ["sample-1.mp4", "sample-2.mp4", "sample-3.mp4"]
