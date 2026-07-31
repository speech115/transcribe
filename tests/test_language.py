#!/usr/bin/env python3
"""Тесты автоопределения языка для transcript metadata."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from language import detect_language


def test_detect_ru():
    assert detect_language("Привет, это русский текст для проверки определения языка.") == "ru"


def test_detect_en():
    assert detect_language("Hello, this is an English transcript for language detection.") == "en"


def test_detect_mixed():
    assert detect_language("Привет, this transcript mixes русский and English phrases.") == "mixed"


def test_detect_too_short_as_auto():
    assert detect_language("да ok") == "auto"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
