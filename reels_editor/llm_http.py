"""OpenAI-호환 chat/completions 러너 (stdlib urllib — 의존성 無)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

TIMEOUT_S = 600


def openai_chat_runner(base_url: str, api_key: str,
                       model: str) -> Callable[[str], str]:
    url = base_url.rstrip("/") + "/chat/completions"

    def run(prompt: str) -> str:
        body = json.dumps({"model": model,
                           "messages": [{"role": "user", "content": prompt}]})
        req = urllib.request.Request(
            url, data=body.encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            raise RuntimeError(
                f"LLM API 오류 {e.code} ({model}): {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"LLM API 연결 실패 ({url}): {e}") from e
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"LLM 응답 형식 오류: {str(data)[:300]}") from e
    return run
