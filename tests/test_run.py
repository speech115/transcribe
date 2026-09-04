import json
import wave
from types import SimpleNamespace
import pytest

from transcribe.run import (RunError, _fetch_youtube_audio, _wav_duration, format_duration,
                            normalize_formats, safe_folder_name, assign_speaker,
                            merge_words_to_turns, run)
from transcribe.engine import EngineError


def test_naming_and_merge():
    assert safe_folder_name("Ты товар соцсети") == "Ты товар соцсети"
    assert safe_folder_name("A/B: C") == "A - B - C"
    assert safe_folder_name("///", "youtube") == "youtube"
    assert assign_speaker(1, 2, [(0, 1.5, "S1"), (1.5, 3, "S2")]) == "S1"
    words = [{"start": 0, "end": 1, "text": "hello"}, {"start": 1.1, "end": 2, "text": "world"}]
    assert merge_words_to_turns(words, [(0, 1, "S1"), (1.5, 3, "S2")])[0]["text"] == "hello"


def test_format_duration():
    assert format_duration(754) == "12:34"
    assert format_duration(3661) == "1:01:01"


def test_safe_folder_name_and_formats():
    assert safe_folder_name("a/b") == "a - b"
    assert normalize_formats("srt,vtt,srt") == ("srt", "vtt")
    with pytest.raises(RunError):
        normalize_formats("ass")


def test_wav_duration_uses_stdlib(tmp_path):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b"\0\0" * 32000)
    assert _wav_duration(path) == 2.0


def test_youtube_download_prints_title_once(monkeypatch, tmp_path):
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/usr/bin/yt-dlp")
    def fake(command, **kwargs):
        (tmp_path / "yt_audio.webm").write_bytes(b"audio")
        return type("Completed", (), {"stdout": "A real title\n"})()
    monkeypatch.setattr("transcribe.run.subprocess.run", fake)
    path, title = _fetch_youtube_audio("https://youtu.be/id", tmp_path)
    assert path.name == "yt_audio.webm" and title == "A real title"


def test_explicit_out_rejects_existing_artifact(monkeypatch, tmp_path):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("old")
    monkeypatch.setattr("transcribe.run.FLUID", tmp_path / "engine")
    (tmp_path / "engine").write_text("x")
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/usr/bin/" + tool)
    with pytest.raises(RunError, match="output already exists; use --overwrite"):
        run(source, out=out)


def test_explicit_out_overwrite_and_stages(monkeypatch, tmp_path):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("old")
    fluid = tmp_path / "engine"
    fluid.write_text("x")
    monkeypatch.setattr("transcribe.run.FLUID", fluid)
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr("transcribe.run._to_wav16k", lambda src, dst: dst.write_bytes(b"wav"))
    monkeypatch.setattr("transcribe.run._wav_duration", lambda path: 1.0)
    fake_result = SimpleNamespace(words=[{"start": 0, "end": 1, "text": "hello"}], segments=[],
                                  speakers=1, language="en", engine="fake",
                                  asr_s=1, diar_s=None, diar_mode=None)
    class FakeEngine:
        def __init__(self, **kwargs): pass
        def transcribe(self, wav, **kwargs):
            if kwargs.get("on_stage"): kwargs["on_stage"]("asr")
            return fake_result
    monkeypatch.setattr("transcribe.run.FluidAudioEngine", FakeEngine)
    stages = []
    result = run(source, out=out, overwrite=True, speakers="off", on_stage=stages.append)
    assert result.transcript_md.read_text() != "old"
    assert stages == ["preparing", "asr", "writing"]
    assert not (out / "progress.json").exists()


def test_auto_diarization_failure_keeps_asr_and_records_fallback(monkeypatch, tmp_path):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    fluid = tmp_path / "engine"
    fluid.write_text("x")
    monkeypatch.setattr("transcribe.run.FLUID", fluid)
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr("transcribe.run._to_wav16k", lambda src, dst: dst.write_bytes(b"wav"))
    monkeypatch.setattr("transcribe.run._wav_duration", lambda path: 1.0)

    calls = {"asr": 0, "diar": 0}

    class FakeEngine:
        def __init__(self, **kwargs): pass
        def transcribe(self, wav, **kwargs):
            calls["asr"] += 1
            calls["diar"] += 1
            if kwargs.get("on_stage"):
                kwargs["on_stage"]("asr")
                kwargs["on_stage"]("diar")
            return SimpleNamespace(
                words=[{"start": 0, "end": 1, "text": "hello"}], segments=[],
                speakers=1, language="en", engine="fake", asr_s=1.0, diar_s=0.2,
                diar_mode="streaming", diar_status="failed", diar_error="CoreML boom",
            )

    monkeypatch.setattr("transcribe.run.FluidAudioEngine", FakeEngine)
    result = run(source, out=out, speakers="auto")
    manifest = json.loads(result.manifest.read_text())
    assert calls == {"asr": 1, "diar": 1}
    assert "hello" in result.transcript_md.read_text()
    assert manifest["diarization"] == {
        "requested": True, "status": "failed", "fallback": "single-speaker",
        "error": "CoreML boom",
    }


def test_explicit_speaker_count_diarization_failure_is_fatal(monkeypatch, tmp_path):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    fluid = tmp_path / "engine"
    fluid.write_text("x")
    monkeypatch.setattr("transcribe.run.FLUID", fluid)
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr("transcribe.run._to_wav16k", lambda src, dst: dst.write_bytes(b"wav"))
    monkeypatch.setattr("transcribe.run._wav_duration", lambda path: 1.0)

    class FakeEngine:
        def __init__(self, **kwargs): pass
        def transcribe(self, wav, **kwargs):
            raise EngineError("diar", "CoreML boom")

    monkeypatch.setattr("transcribe.run.FluidAudioEngine", FakeEngine)
    with pytest.raises(RunError, match="CoreML boom"):
        run(source, out=out, speakers="2")
