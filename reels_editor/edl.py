"""EDL(LLM 생성) 검증·해석. 자막 verbatim 원칙의 집행 지점."""
from __future__ import annotations

from reels_editor.capcut import US


def _seg_index(segments: dict) -> dict:
    return {s["id"]: s for s in segments["segments"]}


def validate_edl(edl_doc: dict, segments: dict) -> list[str]:
    idx = _seg_index(segments)
    errors: list[str] = []
    cuts = edl_doc.get("cuts", [])
    if not cuts:
        errors.append("cuts가 비어 있음 — 최소 1개 비트 필요")
    for c, cut in enumerate(cuts):
        ids = cut.get("seg_ids", [])
        if not ids:
            errors.append(f"cut {c}: seg_ids 비어있음")
        for sid in ids:
            if sid not in idx:
                errors.append(f"cut {c}: 알 수 없는 seg_id '{sid}'")
        # text가 명시됐으면 참조 세그먼트 원문 이어붙임과 문자 단위 일치해야 함
        if "text" in cut and all(sid in idx for sid in ids):
            joined = " ".join(idx[sid]["text"] for sid in ids)
            if cut["text"].strip() != joined.strip():
                errors.append(f"cut {c}: verbatim 불일치 — 원문 그대로만 허용 "
                              f"(기대: {joined!r})")
    return errors


def ordered_segments(edl_doc: dict, segments: dict) -> list[dict]:
    """EDL 순서대로 세그먼트를 펼친다. 영어 원문은 한국어 번역을 자막으로 쓴다."""
    errs = validate_edl(edl_doc, segments)
    if errs:
        raise ValueError("EDL 검증 실패:\n" + "\n".join(errs))
    idx = _seg_index(segments)
    translations = edl_doc.get("subtitle_translations", {})
    if not isinstance(translations, dict):
        translations = {}
    out: list[dict] = []
    for cut in edl_doc["cuts"]:
        for sid in cut["seg_ids"]:
            s = idx[sid]
            out.append({
                "source_start_us": s["source_start_us"],
                "source_end_us": s["source_end_us"],
                "speed": s.get("speed", 1.0),
                "text": str(translations.get(sid) or s.get("text", "")),
            })
    return out


def estimate_duration_s(edl_doc: dict, segments: dict, speed: float) -> float:
    """배속 적용 후 예상 결과물 길이(초)."""
    total_us = sum(o["source_end_us"] - o["source_start_us"]
                   for o in ordered_segments(edl_doc, segments))
    return total_us / US / speed
