"""Upload rendered reels to public media hosting and queue them in Buffer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

BUFFER_GRAPHQL_URL = "https://api.buffer.com"
CLOUDINARY_UPLOAD_URL = "https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"
REQUEST_TIMEOUT_S = 300.0


class BufferPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class BufferPost:
    id: str
    media_url: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "media_url": self.media_url, "text": self.text}


def upload_video(
    video_path: Path,
    *,
    cloud_name: str,
    upload_preset: str,
    client: httpx.Client,
) -> str:
    if not video_path.is_file():
        raise BufferPublishError(f"Buffer 업로드 파일을 찾을 수 없습니다: {video_path}")
    try:
        with video_path.open("rb") as video:
            response = client.post(
                CLOUDINARY_UPLOAD_URL.format(cloud_name=cloud_name),
                data={"upload_preset": upload_preset, "folder": "reels-editor"},
                files={"file": (video_path.name, video, "video/mp4")},
            )
        response.raise_for_status()
        payload = response.json()
    except (OSError, httpx.HTTPError, ValueError) as exc:
        raise BufferPublishError(f"공개 영상 업로드에 실패했습니다: {exc}") from exc
    media_url = payload.get("secure_url") if isinstance(payload, dict) else None
    if not isinstance(media_url, str) or not media_url.startswith("https://"):
        detail = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        raise BufferPublishError(f"공개 영상 URL을 받지 못했습니다{f': {detail}' if detail else ''}")
    return media_url


def create_reel_post(
    *,
    api_key: str,
    channel_id: str,
    media_url: str,
    text: str,
    client: httpx.Client,
) -> BufferPost:
    query = """
      mutation CreateReel($input: CreatePostInput!) {
        createPost(input: $input) {
          ... on PostActionSuccess { post { id text } }
          ... on MutationError { message }
        }
      }
    """
    variables: dict[str, Any] = {
        "input": {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "addToQueue",
            "assets": [{"video": {"url": media_url, "metadata": {"thumbnailOffset": 2000}}}],
            "metadata": {"instagram": {"type": "reel", "shouldShareToFeed": True}},
        }
    }
    try:
        response = client.post(
            BUFFER_GRAPHQL_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise BufferPublishError(f"Buffer API 요청에 실패했습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise BufferPublishError("Buffer API 응답 형식이 올바르지 않습니다.")
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        message = graphql_errors[0].get("message", "알 수 없는 오류")
        raise BufferPublishError(f"Buffer API 오류: {message}")
    result = payload.get("data", {}).get("createPost", {})
    post = result.get("post") if isinstance(result, dict) else None
    if not isinstance(post, dict) or not post.get("id"):
        message = result.get("message", "게시물을 만들지 못했습니다") if isinstance(result, dict) else "게시물을 만들지 못했습니다"
        raise BufferPublishError(f"Buffer 게시 실패: {message}")
    return BufferPost(id=str(post["id"]), media_url=media_url, text=str(post.get("text", text)))


def publish_reel(
    video_path: Path,
    *,
    text: str,
    api_key: str,
    channel_id: str,
    cloud_name: str,
    upload_preset: str,
) -> BufferPost:
    with httpx.Client(timeout=REQUEST_TIMEOUT_S, follow_redirects=True) as client:
        media_url = upload_video(
            video_path,
            cloud_name=cloud_name,
            upload_preset=upload_preset,
            client=client,
        )
        return create_reel_post(
            api_key=api_key,
            channel_id=channel_id,
            media_url=media_url,
            text=text,
            client=client,
        )
