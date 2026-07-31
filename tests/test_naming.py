#!/usr/bin/env python3
"""Тесты имени output-папки."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from run import safe_folder_name


def test_preserves_human_video_title():
    assert safe_folder_name("Ты товар соцсети") == "Ты товар соцсети"


def test_replaces_path_breaking_chars():
    assert safe_folder_name("A/B: C") == "A - B - C"


def test_fallback_for_empty_title():
    assert safe_folder_name("///", "youtube") == "youtube"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
