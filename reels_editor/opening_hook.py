"""Verify opening quotations against consecutive selected source cues."""
import re
import unicodedata

def normalized_quote(text):
    value = unicodedata.normalize('NFKC', text).casefold()
    # Chinese has no word-space requirement; preserve exact characters across cue boundaries.
    value = re.sub(r'([\u4e00-\u9fff])', r' \1 ', value)
    return re.sub(r'[\W_]+', ' ', value).strip()


def opening_quote(summary):
    match = re.match(r'^(?:도입\s*훅|Opening\s+hook|开场钩子)\s*:\s*(?:“(.+?)”|"(.+?)")', summary, re.I)
    return (match.group(1) or match.group(2)).strip() if match else None


def restore_opening_hook_evidence(candidates, segments):
    """Restore nearby omitted cue IDs only when the entire quote is verbatim."""
    rows = segments.get('segments', [])
    positions = {row['id']: i for i, row in enumerate(rows)}
    for candidate in candidates:
        quote = opening_quote(candidate.summary)
        selected = {positions[sid] for sid in candidate.segment_ids if sid in positions}
        if not quote or not selected:
            continue
        # Never search a different topic to justify an unsupported quotation.
        low, high = max(0, min(selected) - 2), min(len(rows), max(selected) + 3)
        tokens = [(word, index) for index in range(low, high)
                  for word in normalized_quote(rows[index]['text']).split()]
        wanted = normalized_quote(quote).split()
        if not wanted:
            continue
        words = [word for word, _ in tokens]
        for offset in range(len(words) - len(wanted) + 1):
            if words[offset:offset + len(wanted)] != wanted:
                continue
            first, last = tokens[offset][1], tokens[offset + len(wanted) - 1][1]
            evidence = set(range(first, last + 1))
            if evidence & selected:
                candidate.segment_ids = [rows[index]['id'] for index in sorted(selected | evidence)]
                break


def opening_hook_errors(candidates, segments):
    """Check source quotations, not whether a subjective hook will perform well."""
    rows = segments.get('segments', [])

    errors = []
    for candidate in candidates:
        quote = opening_quote(candidate.summary)
        if not quote:
            errors.append(f'{candidate.id}: summary must begin with Opening hook: “an exact source quotation”.')
            continue
        selected = set(candidate.segment_ids)
        runs, previous = [], -2
        for index, row in enumerate(rows):
            if row['id'] not in selected:
                continue
            if index != previous + 1:
                runs.append([])
            runs[-1].append(row['text'])
            previous = index
        quoted = normalized_quote(quote)
        if not quoted or not any(f' {quoted} ' in f' {normalized_quote(" ".join(run))} ' for run in runs):
            errors.append(f'{candidate.id}: the opening quote must match consecutive selected source captions. Preserve the original wording, grammar and repetitions.')
        if re.match(r"^(?:they(?:['’](?:re|ve|ll|d))?|their|he|she|그들|그것|그때)(?:\b|은|는|이|가)", quote, re.I):
            errors.append(f'{candidate.id}: the opening quote starts with a pronoun without an antecedent. Choose speech whose subject is clear to a new viewer.')
    return errors

