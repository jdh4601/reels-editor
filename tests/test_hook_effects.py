from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from reels_editor import hook_effects as hook, render, quality_review as quality
from reels_editor.caption_timing import extract_audio
from reels_editor.style import load_style
from test_caption_timing import fixture

SOUND = Path(__file__).resolve().parents[1] / 'reels_editor/resources/styles/assets/hook-whoosh.wav'


def prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'DEFAULT_SOUND', SOUND)
    doc, segments, plan = fixture()
    doc['caption_timing'] = plan
    return hook.prepare(doc, segments, 1, tmp_path,
        runner=lambda _: json.dumps({'anchor_word': 1, 'reason': '고객이 원하는 것을 강조'})), segments


def test_selects_real_word_and_invalidates_changed_cuts_or_sound(monkeypatch, tmp_path):
    doc, segments = prepared(monkeypatch, tmp_path)
    effect = doc['hook_effect']
    assert effect['anchor_s'] == 1 and effect['start_s'] == 1
    assert effect['zoom'] == 1.3 and effect['sound_start_s'] == .82
    assert effect['zoom_in_s'] == .1 and effect['zoom_peak_s'] == 1.1
    assert effect['hold_end_s'] == 1.75 and effect['end_s'] == 1.93
    changed = deepcopy(doc)
    changed['source_trim_us'] = {'s1': {'start': 100000}}
    with pytest.raises(ValueError, match="plan"):
        hook.validate(changed, segments, 1)
    doc['hook_effect']['sound_sha256'] = 'changed'
    with pytest.raises(ValueError, match='file has changed'):
        hook.validate(doc, segments, 1)


@pytest.mark.parametrize('field,value', [('zoom', 1.2), ('zoom_in_s', .2),
    ('start_s', 1.1), ('zoom_peak_s', 1.2), ('version', 1)])
def test_rejects_old_zoom_or_added_delay(monkeypatch, tmp_path, field, value):
    doc, segments = prepared(monkeypatch, tmp_path)
    doc['hook_effect'][field] = value
    with pytest.raises(ValueError, match="opening-effect plan"):
        hook.validate(doc, segments, 1)


def test_valid_effect_is_preserved_without_new_feedback(monkeypatch,tmp_path):
    doc,segments=prepared(monkeypatch,tmp_path)
    def unexpected(_prompt):
        raise AssertionError('이미 검증된 강조 단어를 다시 선택함')
    assert hook.prepare(doc,segments,1,tmp_path,runner=unexpected) == doc


def test_clean_onset_evidence_cannot_be_changed(monkeypatch,tmp_path):
    import wave
    from array import array
    doc,segments,plan=fixture();doc['caption_timing']=plan
    # Give the 1.0s ASR start a measured 0.9s voice onset after 40ms silence.
    clean=tmp_path/'clean.wav';rate=16000
    with wave.open(str(clean),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        wav.writeframes(array('h',(0 if .86<=i/rate<.9 else 3000 for i in range(rate*4))).tobytes())
    segments['video_path']='source.mp4'
    monkeypatch.setattr(hook,'DEFAULT_SOUND',SOUND)
    monkeypatch.setattr(hook,'extract_audio',lambda *_a,**_k:clean)
    result=hook.prepare(doc,segments,1,tmp_path,runner=lambda _:json.dumps({'anchor_word':1,'reason':'핵심어'}))
    assert result['hook_effect']['anchor_s'] == .9
    result['hook_effect']['clean_voice_onset']['onset_s']=.8
    with pytest.raises(ValueError,match="original measurement"):
        hook.validate(result,segments,1)


@pytest.mark.parametrize('index', [True, -1, 99, 3])
def test_no_fallback_to_fabricated_or_late_word(monkeypatch, tmp_path, index):
    monkeypatch.setattr(hook, 'DEFAULT_SOUND', SOUND)
    doc, segments, plan = fixture()
    plan['words'][3]['start'] = 3.1
    doc['caption_timing'] = plan
    with pytest.raises(ValueError, match="select an opening emphasis word"):
        hook.prepare(doc, segments, 1, tmp_path,
            runner=lambda _: json.dumps({'anchor_word': index, 'reason': '선택'}))


def test_opus_cannot_omit_effect_checks():
    result = {'checks': {key: {'verdict': 'pass', 'evidence': '시간과 영상 근거'}
                        for key in quality.CHECKS}, 'issues': []}
    with pytest.raises(ValueError, match="missing"):
        quality.parse_review(json.dumps(result), 4, quality.CHECKS + hook.CHECKS)
    result['checks'].update({key: {'verdict': 'pass', 'evidence': '확대 전후·파형 근거'} for key in hook.CHECKS})
    assert quality.parse_review(json.dumps(result), 4, quality.CHECKS + hook.CHECKS)


def test_hook_selection_excludes_word_interval_containing_a_long_pause(monkeypatch,tmp_path):
    monkeypatch.setattr(hook,'DEFAULT_SOUND',SOUND)
    doc,segments,plan=fixture();doc['caption_timing']=plan
    plan['words'][1].update(start=1,end=1.7)
    def choose(prompt):
        evidence=json.loads(prompt.split('\n',1)[1])
        assert 1 not in evidence['eligible_word_indices']
        return json.dumps({'anchor_word':2,'reason':'실제 발화 구간이 짧고 명확한 핵심어'})
    result=hook.prepare(doc,segments,1,tmp_path,runner=choose)
    assert result['hook_effect']['anchor_word']==2


def test_opus_receives_effect_frames_and_cannot_override_missing_sound(monkeypatch, tmp_path):
    from test_quality_review import setup_review
    video, doc, segments, assets, _ = setup_review(monkeypatch, tmp_path)
    effect_doc, _ = prepared(monkeypatch, tmp_path/'plan')
    doc['hook_effect'] = effect_doc['hook_effect']
    monkeypatch.setattr(hook, 'render_evidence', lambda *_a: dict(
        effect=doc['hook_effect'], sound_detected=False, sound_correlation=.01))
    def sheets(_video, _groups, _duration, _work, *, extra_times):
        assert len(extra_times) == 13
        for at in (1,1.02,1.05,1.1,1.75,1.84,1.93,1.96):
            assert any(t == pytest.approx(at) for t in extra_times)
        assert min(extra_times) < 1 and max(extra_times) > 1.93
        return [tmp_path/'effects.jpg'], extra_times
    monkeypatch.setattr(quality, 'make_sheets', sheets)
    def source_sheet(_doc, _segments, _speed, _work, *, extra_times):
        assert any(t == pytest.approx(.88) for t in extra_times)
        assert any(t == pytest.approx(1.13) for t in extra_times)
        return tmp_path/'source.jpg'
    monkeypatch.setattr(quality, 'source_hook_sheet', source_sheet)
    def reviewer(prompt, images):
        assert 'hook_zoom,hook_whoosh' in prompt
        assert '0.1초 만에 100→130%' in prompt
        assert '동시에 지연 없이' in prompt
        assert 'sound_correlation' in prompt and '직접 오디오를 들었다' in prompt
        assert images[0] == tmp_path/'effects.jpg'
        return json.dumps({'checks': {key: {'verdict': 'pass', 'evidence': '제공된 근거'}
                          for key in quality.CHECKS+hook.CHECKS}, 'issues': []})
    result = quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',reviewer=reviewer)
    assert not result['passed']
    assert any('whoosh' in row['evidence'] for row in result['machine_issues'])


@pytest.mark.parametrize('quiet', [True, False])
def test_refine_coarse_asr_only_with_unambiguous_clean_voice_edge(tmp_path, quiet):
    import wave
    from array import array
    audio=tmp_path/'clean.wav'; rate=16000
    signal=array('h', (0 if quiet and 2.78 <= i/rate < 2.82 else 3000 for i in range(rate*4)))
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(signal.tobytes())
    measured=hook.measure_onset(audio, {'start':2.92})
    assert measured['onset_s'] == (2.82 if quiet else 2.92)
    assert measured['asr_start_s'] == 2.92


def test_manifest_preserves_effect_and_legacy_manifests_still_load(monkeypatch, tmp_path):
    doc, _ = prepared(monkeypatch, tmp_path)
    assets = render.RenderAssets(tmp_path/'source', tmp_path/'wm', [], [], tmp_path, [],
                                 hook_effect=doc['hook_effect'])
    assert render.RenderAssets.from_dict(assets.to_dict()).hook_effect == doc['hook_effect']
    legacy = assets.to_dict()
    legacy.pop('hook_effect')
    assert render.RenderAssets.from_dict(legacy).hook_effect is None


@pytest.mark.parametrize('source_fps', [24, 30])
def test_real_mp4_zoom_keeps_bars_fixed_and_detects_actual_whoosh(monkeypatch, tmp_path, source_fps):
    """Exercise the real encoder graph, audio mix, receipt and decoded frames."""
    from PIL import Image, ImageChops, ImageStat
    doc, segments = prepared(monkeypatch, tmp_path/'plan')
    source = tmp_path/'source.mp4'
    render._ffmpeg(['-f','lavfi','-i',f'testsrc2=s=320x480:r={source_fps}:d=4',
                    '-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=4',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)])
    style = replace(load_style(Path(__file__).resolve().parents[1] / 'reels_editor/resources/styles/default.yaml'), canvas=(320,568), top_bar=44, bottom_bar=44)
    # Freeze source imagery so visual differences measure the animation only.
    graph = ('[0:v]trim=0:4,setpts=PTS-STARTPTS,loop=loop=-1:size=1:start=0,trim=duration=4,'
             'scale=320:480,pad=320:568:0:44:black[v];[0:a]atrim=0:4,asetpts=PTS-STARTPTS[a]')
    base_filter=tmp_path/'base.txt';base_filter.write_text(graph)
    png=tmp_path/'transparent.png';Image.new('RGBA',style.canvas).save(png)
    monkeypatch.setattr(render,'render_title_png',lambda *_a,**_k:png)
    monkeypatch.setattr(render,'render_watermark_png',lambda *_a,**_k:png)
    assets=render.RenderAssets(source,png,[],[],tmp_path,[],source=source,
        base_filter=base_filter,total_s=4,hook_effect=doc['hook_effect'])
    out=render.render_overlay_variant(assets,title_text='훅',keyword='',style=style,
                                      out_path=tmp_path/'final.mp4',subtitles_enabled=False)
    render.verify_render_output(out,style.canvas,4)
    work=tmp_path/'review';work.mkdir()
    extract_audio(out,work/'final-audio.wav',duration=4)
    evidence=hook.render_evidence(out,doc,segments,assets,1,work)
    assert evidence['sound_detected'], evidence
    frames=[]
    for i, t in enumerate((.5,1.1,2.2,.967,1.034)):
        path=tmp_path/f'frame-{i}.png'
        render._ffmpeg(['-ss',str(t),'-i',str(out),'-frames:v','1',str(path)])
        frames.append(Image.open(path).convert('RGB'))
    assert max(ImageStat.Stat(ImageChops.difference(frames[0].crop((0,0,320,44)),
                                                    frames[1].crop((0,0,320,44)))).mean) < 2
    assert sum(ImageStat.Stat(ImageChops.difference(frames[0],frames[1])).mean) > 20
    assert sum(ImageStat.Stat(ImageChops.difference(frames[0],frames[2])).mean) < 8
    # No pre-roll and no waiting after the word: the very next frame is zooming.
    assert sum(ImageStat.Stat(ImageChops.difference(frames[0],frames[3])).mean) < 8
    assert sum(ImageStat.Stat(ImageChops.difference(frames[0],frames[4])).mean) > 5
    assert sum(ImageStat.Stat(ImageChops.difference(frames[1],frames[4])).mean) > 3
    # A stale receipt cannot approve a different final file.
    with out.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError,match="record"):
        hook.render_evidence(out,doc,segments,assets,1,work)
