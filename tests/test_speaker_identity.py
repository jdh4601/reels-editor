import json

from reels_editor import speaker_identity
from reels_editor.storyteller import StorylineResult, format_speaker_label, normalize_speaker_data


def _result():
    return StorylineResult(0, "원칙형", {"speaker": {"name": "차마스", "role": ""}})


def _response():
    return {"speakers": [{
        "name": "차마스", "display_name": "차마스 팔리하피티야",
        "source_name": "Chamath Palihapitiya", "company": "Social Capital",
        "role": "창업자", "alternate_role": "",
        "evidence": "Chamath Palihapitiya is the founder of Social Capital.",
        "source_url": "https://www.socialcapital.com/about",
    }]}


def test_verified_search_adds_role_and_retains_provenance(tmp_path):
    result = _result()
    response = _response()
    speaker_identity.enrich_speakers(
        [result], {"source_channel": "Chamath Palihapitiya"},
        cache_path=tmp_path / "lookup.json", runner=lambda _: json.dumps(response),
        fetch=lambda _: response["speakers"][0]["evidence"])
    speaker = result.doc["speaker"]
    assert format_speaker_label(speaker) == "차마스 팔리하피티야 (Social Capital 창업자)"
    assert normalize_speaker_data(speaker)["source_url"] == response["speakers"][0]["source_url"]


def test_fabricated_quote_or_wrong_person_is_not_used(tmp_path):
    for page in ["no supporting evidence", "Someone Else is the founder of Social Capital."]:
        result = _result()
        speaker_identity.enrich_speakers(
            [result], {}, cache_path=tmp_path / "lookup.json",
            runner=lambda _: json.dumps(_response()), fetch=lambda _: page)
        assert format_speaker_label(result.doc["speaker"]) == "차마스"
        assert json.loads((tmp_path / "lookup.json").read_text())["errors"]
        (tmp_path / "lookup.json").unlink()


def test_search_failure_does_not_block_rendering(tmp_path):
    def fail(_):
        raise RuntimeError("search unavailable")
    result = _result()
    speaker_identity.enrich_speakers([result], {}, cache_path=tmp_path / "lookup.json", runner=fail)
    assert format_speaker_label(result.doc["speaker"]) == "차마스"


def test_verified_cache_avoids_repeated_searches(tmp_path):
    calls = []
    def runner(prompt):
        calls.append(prompt)
        return json.dumps(_response())
    for _ in range(2):
        speaker_identity.enrich_speakers(
            [_result()], {}, cache_path=tmp_path / "lookup.json", runner=runner,
            fetch=lambda _: _response()["speakers"][0]["evidence"])
    assert len(calls) == 1


def test_already_grounded_role_does_not_trigger_search(tmp_path):
    result = _result()
    result.doc["speaker"] = _response()["speakers"][0]
    def fail(_):
        raise AssertionError("unneeded search")
    speaker_identity.enrich_speakers([result], {}, cache_path=tmp_path / "lookup.json", runner=fail)


def test_private_source_url_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        speaker_identity.fetch_source_text("https://127.0.0.1/private")
