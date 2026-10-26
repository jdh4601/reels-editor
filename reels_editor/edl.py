"""EDL(LLM 생성) 검증·해석. 자막 verbatim 원칙의 집행 지점."""
from __future__ import annotations

from reels_editor.timebase import US


def _seg_index(segments: dict) -> dict:
    return {s["id"]: s for s in segments["segments"]}


def validate_edl(edl_doc: dict, segments: dict) -> list[str]:
    idx = _seg_index(segments)
    errors: list[str] = []
    cuts = edl_doc.get("cuts", [])
    selected_ids: list[str] = []
    if not cuts:
        errors.append("cuts is empty; at least one beat is required")
    for c, cut in enumerate(cuts):
        ids = cut.get("seg_ids", [])
        selected_ids.extend(str(sid) for sid in ids)
        if not ids:
            errors.append(f"cut {c}: seg_ids is empty")
        for sid in ids:
            if sid not in idx:
                errors.append(f"cut {c}: unknown seg_id '{sid}'")
        # text가 명시됐으면 참조 세그먼트 원문 이어붙임과 문자 단위 일치해야 함
        if "text" in cut and all(sid in idx for sid in ids):
            joined = " ".join(idx[sid]["text"] for sid in ids)
            if cut["text"].strip() != joined.strip():
                errors.append(f"cut {c}: verbatim 불일치 — 원문 그대로만 허용 "
                              f"(기대: {joined!r})")
    known_ids = [sid for sid in selected_ids if sid in idx]
    trims = edl_doc.get('source_trim_us', {})
    if not isinstance(trims, dict):
        errors.append("source_trim_us must be an object")
    else:
        for sid, trim in trims.items():
            if sid not in known_ids or not isinstance(trim, dict):
                errors.append("The cut-boundary segment ID is not selected")
                continue
            a, b = trim.get('start', 0), trim.get('end', 0)
            if (type(a) is not int or type(b) is not int or a < 0 or b < 0 or
                a + b >= idx[sid]['source_end_us'] - idx[sid]['source_start_us']):
                errors.append("The cut-boundary repair exceeds the original segment")
    focus = edl_doc.get('focus_overrides', {})
    if not isinstance(focus, dict) or any(sid not in known_ids or side not in ('left','center','right')
                                          for sid,side in focus.items()):
        errors.append("Invalid speaker-crop evidence segment or direction")
    for previous_id, current_id in zip(known_ids, known_ids[1:]):
        if idx[current_id]["source_start_us"] < idx[previous_id]["source_start_us"]:
            errors.append(
                f"Selected segment IDs are not in source order: "
                f"{previous_id} → {current_id}"
            )
            break
    return errors


def ordered_segments(edl_doc: dict, segments: dict) -> list[dict]:
    """EDL 순서대로 세그먼트를 펼친다. 영어 원문은 한국어 번역을 자막으로 쓴다."""
    errs = validate_edl(edl_doc, segments)
    if errs:
        raise ValueError("EDL validation failed:\n" + "\n".join(errs))
    idx = _seg_index(segments)
    translations = edl_doc.get("subtitle_translations", {})
    if not isinstance(translations, dict):
        translations = {}
    out: list[dict] = []
    for cut in edl_doc["cuts"]:
        for sid in cut["seg_ids"]:
            s = idx[sid]
            trim = edl_doc.get('source_trim_us', {}).get(sid, {})
            out.append({
                "source_start_us": s["source_start_us"] + trim.get('start', 0),
                "source_end_us": s["source_end_us"] - trim.get('end', 0),
                "speed": s.get("speed", 1.0),
                "text": str(translations.get(sid) or s.get("text", "")),
            })
    return out


def estimate_duration_s(edl_doc: dict, segments: dict, speed: float) -> float:
    """배속 적용 후 예상 결과물 길이(초)."""
    total_us = sum(o["source_end_us"] - o["source_start_us"]
                   for o in ordered_segments(edl_doc, segments))
    return total_us / US / speed
