"""Isolated, cancellable local ASR worker; release GPU memory after each clip."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('audio')
    parser.add_argument('output')
    parser.add_argument('--language', default='')
    args = parser.parse_args()
    import mlx_whisper
    result = mlx_whisper.transcribe(
        args.audio, path_or_hf_repo='mlx-community/whisper-large-v3-turbo',
        language=args.language or None, word_timestamps=True,
        condition_on_previous_text=False, temperature=0.0,
        hallucination_silence_threshold=1.0,
    )
    words = [word for segment in result.get('segments', [])
             for word in segment.get('words', [])]
    Path(args.output).write_text(json.dumps({
        'language': result.get('language'), 'words': words,
        'engine': 'mlx-whisper/large-v3-turbo',
    }, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
