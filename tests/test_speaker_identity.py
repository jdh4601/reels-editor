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
            [_result()], {"source_title": "Chamath Palihapitiya interview"}, cache_path=tmp_path / "lookup.json", runner=runner,
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


def test_name_in_heading_and_pronoun_role_paragraph_are_grounded(tmp_path):
    result = _result()
    response = _response()
    entry = response['speakers'][0]
    entry['evidence'] = 'He is the founder of Social Capital.'
    speaker_identity.enrich_speakers([result], {'source_title': 'Chamath Palihapitiya interview'},
        cache_path=tmp_path / 'lookup.json', required=True,
        runner=lambda _: json.dumps(response),
        fetch=lambda _: 'Chamath Palihapitiya\nHe is the founder of Social Capital.')
    assert format_speaker_label(result.doc['speaker']) == '차마스 팔리하피티야 (Social Capital 창업자)'


def test_required_role_reuses_recent_failure_without_another_search(tmp_path):
    import pytest
    calls = []
    def fail(_):
        calls.append(1)
        raise RuntimeError('search unavailable')
    for required in [False, True]:
        if required:
            with pytest.raises(ValueError, match="verify the role using web sources"):
                speaker_identity.enrich_speakers([_result()], {}, cache_path=tmp_path / 'lookup.json', runner=fail, required=True)
        else:
            speaker_identity.enrich_speakers([_result()], {}, cache_path=tmp_path / 'lookup.json', runner=fail)
    assert len(calls) == 1


def test_alternative_source_is_verified_after_first_quote_fails(tmp_path):
    result = _result()
    response = _response()
    valid = response['speakers'][0]
    response['speakers'].insert(0, {**valid, 'source_url': 'https://example.com/broken'})
    speaker_identity.enrich_speakers([result], {'source_title': 'Chamath Palihapitiya interview'},
        cache_path=tmp_path / 'lookup.json', required=True, runner=lambda _: json.dumps(response),
        fetch=lambda url: 'no supporting quote' if 'broken' in url else valid['evidence'])
    assert format_speaker_label(result.doc['speaker']) == '차마스 팔리하피티야 (Social Capital 창업자)'


def test_parallel_reels_reuse_one_verified_lookup(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import time
    calls = []
    def runner(prompt):
        calls.append(prompt)
        time.sleep(0.02)
        return json.dumps(_response())
    results = [_result() for _ in range(6)]
    def enrich(result):
        speaker_identity.enrich_speakers(
            [result], {"source_title": "Chamath Palihapitiya interview"},
            cache_path=tmp_path / "lookup.json", required=True, runner=runner,
            fetch=lambda _: _response()["speakers"][0]["evidence"])
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(enrich, results))
    assert len(calls) == 1
    assert all("Social Capital" in format_speaker_label(r.doc["speaker"]) for r in results)
    assert not json.loads((tmp_path / "lookup.json").read_text())["errors"]


def test_failed_quote_does_not_launch_another_search_in_same_attempt(tmp_path):
    import pytest
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        response = _response()
        response['speakers'][0]['evidence'] = 'Invented quote'
        return json.dumps(response)
    with pytest.raises(ValueError, match='verify the role'):
        speaker_identity.enrich_speakers(
            [_result()], {'source_title': 'Chamath Palihapitiya interview'},
            cache_path=tmp_path / 'lookup.json', required=True, runner=runner,
            fetch=lambda _: _response()['speakers'][0]['evidence'])
    assert len(prompts) == 1


def _unknown_clip():
    return StorylineResult(0, "전략형", {
        "speaker": {"name": "알 수 없음"},
        "cuts": [{"seg_ids": ["clip"]}],
    })


def _group_source():
    return {"source_description": "Grant, Bart and Ejay run Dad Gang. The founders of Dad Gang answer every DM.",
            "segments": [{"id": "clip", "text": "We still answer every DM ourselves."}]}


def _group_response(prompt):
    request = json.loads(prompt.split('\n', 1)[1])
    return json.dumps({"speakers": [{"clip_id": clip["id"], "identity_scope": "group",
        "name": "Dad Gang", "company": "Dad Gang", "role": "창업자",
        "evidence_source": "source_description", "evidence": "The founders of Dad Gang answer every DM."}
        for clip in request["clips"]]})


def test_unknown_speaker_resolves_to_source_grounded_group_without_assigning_a_guest(tmp_path):
    result = _unknown_clip()
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        return _group_response(prompt)
    for current in [result, _unknown_clip()]:
        speaker_identity.enrich_speakers([current], _group_source(), cache_path=tmp_path / 'lookup.json',
                                        required=True, runner=runner)
        assert format_speaker_label(current.doc['speaker']) == 'Dad Gang 공동 창업자'
        assert current.doc['speaker']['identity_scope'] == 'group'
        assert current.doc['speaker']['evidence_source'] == 'source_description'
    assert len(prompts) == 1
    assert '"names"' not in prompts[0]
    assert 'We still answer every DM ourselves.' in prompts[0]


def test_unidentified_names_never_reach_person_search(tmp_path):
    import pytest
    for name in ['알 수 없음', '미상', '이름 미상', '인터뷰 화자', 'Unknown', 'N/A', '']:
        result = _unknown_clip()
        result.doc['speaker']['name'] = name
        def fail(_):
            raise AssertionError('A placeholder is not a searchable person')
        with pytest.raises(ValueError, match="speaker name could not be verified"):
            speaker_identity.enrich_speakers([result], {}, cache_path=tmp_path / 'lookup.json',
                                            required=True, runner=fail)
        assert format_speaker_label(result.doc['speaker']) == ''


def test_context_identity_rejects_fabricated_quote_and_unsupported_group(tmp_path):
    import pytest
    for evidence in ['The founders of Other Company answer every DM.',
                     'Grant, Bart and Ejay run Dad Gang.']:
        result = _unknown_clip()
        def runner(prompt):
            response = json.loads(_group_response(prompt))
            response['speakers'][0]['evidence'] = evidence
            return json.dumps(response)
        with pytest.raises(ValueError, match="speaker name could not be verified"):
            speaker_identity.enrich_speakers([result], _group_source(), cache_path=tmp_path / 'lookup.json',
                                            required=True, runner=runner)
        assert format_speaker_label(result.doc['speaker']) == ''


def test_context_cache_is_scoped_to_source_and_selected_clip(tmp_path):
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        return _group_response(prompt)
    for text in ['We answer every DM.', 'We personally answer every email.']:
        source = _group_source()
        source['segments'][0]['text'] = text
        speaker_identity.enrich_speakers([_unknown_clip()], source, cache_path=tmp_path / 'lookup.json',
                                        required=True, runner=runner)
    assert len(prompts) == 2
