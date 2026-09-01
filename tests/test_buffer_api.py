from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from reels_editor import buffer_api


def test_upload_video_returns_cloudinary_secure_url(tmp_path: Path) -> None:
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"video")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.cloudinary.com/v1_1/demo/video/upload"
        assert b"unsigned-preset" in request.read()
        return httpx.Response(200, json={"secure_url": "https://res.cloudinary.com/demo/video/upload/reel.mp4"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = buffer_api.upload_video(
            video, cloud_name="demo", upload_preset="unsigned-preset", client=client
        )

    assert result.endswith("/reel.mp4")


def test_create_reel_post_queues_instagram_reel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer buffer-secret"
        payload = json.loads(request.read())
        post_input = payload["variables"]["input"]
        assert post_input["channelId"] == "instagram-channel"
        assert post_input["mode"] == "addToQueue"
        assert post_input["metadata"]["instagram"] == {
            "type": "reel", "shouldShareToFeed": True,
        }
        return httpx.Response(200, json={
            "data": {"createPost": {"post": {"id": "post-1", "text": "caption"}}}
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        post = buffer_api.create_reel_post(
            api_key="buffer-secret",
            channel_id="instagram-channel",
            media_url="https://cdn.example/reel.mp4",
            text="caption",
            client=client,
        )

    assert post.id == "post-1"


def test_create_reel_post_surfaces_graphql_mutation_error() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"data": {"createPost": {"message": "daily limit reached"}}}
    ))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(buffer_api.BufferPublishError, match="daily limit reached"):
            buffer_api.create_reel_post(
                api_key="key", channel_id="channel",
                media_url="https://cdn.example/reel.mp4", text="caption", client=client,
            )
