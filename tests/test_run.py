import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from run import RunError, format_duration, normalize_formats, safe_folder_name


def test_format_duration():
    assert format_duration(754) == "12:34"
    assert format_duration(3661) == "1:01:01"


def test_safe_folder_name_and_formats():
    assert safe_folder_name("a/b") == "a - b"
    assert normalize_formats("srt,vtt,srt") == ("srt", "vtt")
    try:
        normalize_formats("ass")
    except RunError:
        pass
    else:
        raise AssertionError("unsupported format should fail")
