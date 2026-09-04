import os
import sys
import wave
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from run import RunError, _fetch_youtube_audio, _wav_duration, format_duration, normalize_formats, safe_folder_name, run


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


def test_wav_duration_uses_stdlib(tmp_path):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b"\0\0" * 32000)
    assert _wav_duration(path) == 2.0


def test_youtube_download_prints_title_once(monkeypatch, tmp_path):
    monkeypatch.setattr("run.shutil.which", lambda tool: "/usr/bin/yt-dlp")
    def fake(command, **kwargs):
        (tmp_path / "yt_audio.webm").write_bytes(b"audio")
        return type("Completed", (), {"stdout": "A real title\n"})()
    monkeypatch.setattr("run.subprocess.run", fake)
    path, title = _fetch_youtube_audio("https://youtu.be/id", tmp_path)
    assert path.name == "yt_audio.webm" and title == "A real title"


def test_explicit_out_rejects_existing_artifact(monkeypatch, tmp_path):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("old")
    monkeypatch.setattr("run.FLUID", tmp_path / "engine")
    (tmp_path / "engine").write_text("x")
    monkeypatch.setattr("run.shutil.which", lambda tool: "/usr/bin/" + tool)
    try:
        run(source, out=out)
    except RunError as exc:
        assert str(exc) == "output already exists; use --overwrite"
    else:
        raise AssertionError("existing explicit output should fail")


def test_explicit_out_overwrite_and_stages(monkeypatch, tmp_path):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("old")
    fluid = tmp_path / "engine"
    fluid.write_text("x")
    monkeypatch.setattr("run.FLUID", fluid)
    monkeypatch.setattr("run.shutil.which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr("run._to_wav16k", lambda src, dst: dst.write_bytes(b"wav"))
    monkeypatch.setattr("run._wav_duration", lambda path: 1.0)
    fake_result = SimpleNamespace(words=[{"start": 0, "end": 1, "text": "hello"}], segments=[],
                                  speakers=1, language="en", engine="fake",
                                  timings=SimpleNamespace(asr_s=1, diar_s=None), diar_mode=None)
    class FakeEngine:
        def __init__(self, **kwargs): pass
        def transcribe(self, wav, **kwargs):
            if kwargs.get("on_stage"): kwargs["on_stage"]("asr")
            return fake_result
    monkeypatch.setattr("run.FluidAudioEngine", FakeEngine)
    stages = []
    result = run(source, out=out, overwrite=True, speakers="off", on_stage=stages.append)
    assert result.transcript_md.read_text() != "old"
    assert stages == ["preparing", "asr", "writing"]
    assert not (out / "progress.json").exists()
