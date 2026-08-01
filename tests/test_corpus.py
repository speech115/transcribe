#!/usr/bin/env python3
"""Tests for corpus collection and legacy-manifest compatibility."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from collect_corpus import collect, summarize


def test_collect_projects_manifest_into_corpus_row():
    with tempfile.TemporaryDirectory() as td:
        manifest = Path(td) / "run" / "manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({
            "source": "call.m4a", "duration": 120.0, "speakers": 2,
            "language": "ru", "engine": "fake",
            "generated": "2026-08-01T00:00:00Z", "out_dir": str(manifest.parent),
            "timings_s": {"prep_s": 1.0, "asr_s": 4.0, "diar_s": 2.0},
            "asr_rtf": 30.0, "asr_model": "v3", "diar_mode": "streaming",
            "speakers_arg": "auto", "words": 10, "turns": 2,
            "engine_binary": "/tmp/fake",
        }))

        rows = collect(Path(td))

    assert len(rows) == 1
    assert rows[0]["source"] == "call.m4a"
    assert rows[0]["prep_s"] == 1.0
    assert rows[0]["measured_rtf"] == 30.0
    assert rows[0]["manifest_path"] == str(manifest)


def test_summarize_handles_missing_language():
    summary = summarize([{"language": "ru"}, {"language": None}])

    assert "ru: 1" in summary
    assert "unknown: 1" in summary


if __name__ == "__main__":
    test_summarize_handles_missing_language()
    print("ok: test_summarize_handles_missing_language")
