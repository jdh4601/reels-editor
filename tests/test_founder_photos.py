import io
import json

from PIL import Image

from reels_editor.founder_photos import find_photos


def test_search_photos_require_public_source_evidence_and_actual_image_url(tmp_path):
    image = io.BytesIO()
    Image.new('RGB', (600, 800), 'green').save(image, 'JPEG')
    entry = {'source_url': 'https://company.example/team', 'image_url': 'https://company.example/founder.jpg',
             'source_name': 'Jane Doe', 'evidence': 'Jane Doe founded Example.'}
    def fetch(url, *, image=False):
        if image:
            return globals_image, 'utf-8'
        return b'<p>Jane Doe founded Example.</p><img src="/founder.jpg">', 'utf-8'
    globals_image = image.getvalue()
    photos, warnings = find_photos({'name': '제인 도', 'company': 'Example'}, {'source_title': 'Jane Doe interview'}, tmp_path,
        runner=lambda _: json.dumps({'photos': [entry, {**entry, 'image_url': 'https://company.example/invented.jpg'}]}), fetch=fetch)
    assert len(photos) == 1 and photos[0]['source_url'] == entry['source_url']
    assert Image.open(photos[0]['path']).size == (600, 800)
    assert warnings


def test_unknown_founder_or_failed_search_returns_explicit_warning(tmp_path):
    assert find_photos({}, {}, tmp_path)[0] == []
    def fail(_):
        raise RuntimeError('search failed')
    photos, warnings = find_photos({'name': 'Jane'}, {}, tmp_path, runner=fail)
    assert photos == [] and warnings
