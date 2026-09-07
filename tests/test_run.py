import json
import os
import wave
from pathlib import Path
from random import Random
from types import SimpleNamespace
import pytest

from transcribe.run import (RunError, _fetch_youtube_audio, _wav_duration, format_duration,
                            normalize_formats, safe_folder_name, assign_speaker,
                            merge_words_to_turns, run, _publish_artifacts, _render_subtitles)
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


@pytest.mark.parametrize("artifact", ["transcript.md", "transcript.json", "manifest.json", "transcript.srt", "transcript.vtt"])
def test_explicit_out_rejects_existing_artifact(monkeypatch, tmp_path, artifact):
    source = tmp_path / "call.m4a"
    source.write_bytes(b"audio")
    out = tmp_path / "out"
    out.mkdir()
    (out / artifact).write_text("old")
    monkeypatch.setattr("transcribe.run.FLUID", tmp_path / "engine")
    (tmp_path / "engine").write_text("x")
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/usr/bin/" + tool)
    with pytest.raises(RunError, match="output already exists; use --overwrite"):
        run(source, out=out)
    assert (out / artifact).read_text() == "old"


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
                                  asr_s=1, diar_s=None, diar_mode=None,
                                  diar_status="skipped", diar_error=None)
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

    class FakeEngine:
        def __init__(self, **kwargs): pass
        def transcribe(self, wav, **kwargs):
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


@pytest.mark.parametrize("failure", [None, "write", "publish", "interrupt"])
def test_publication_preserves_unrelated_files_and_rolls_back(monkeypatch, tmp_path, failure):
    out = tmp_path / "out"
    out.mkdir()
    originals = {"transcript.md": "old text", "manifest.json": "old manifest", "transcript.srt": "old captions"}
    for name, content in originals.items():
        (out / name).write_text(content)
    (out / "notes").mkdir()
    (out / "notes/transcript.md").write_text("unrelated notes")
    source = tmp_path / "original.txt"
    source.write_text("original")
    (out / "link").symlink_to(source)
    write, replace = Path.write_text, Path.replace
    def failing_write(path, content, *args, **kwargs):
        if failure == "write" and path.name == "manifest.json":
            raise OSError("disk full")
        return write(path, content, *args, **kwargs)
    def failing_replace(path, target):
        if path.parent.name == "new" and path.name == "manifest.json" and failure in ("publish", "interrupt"):
            raise KeyboardInterrupt() if failure == "interrupt" else OSError("rename failed")
        return replace(path, target)
    monkeypatch.setattr(Path, "write_text", failing_write)
    monkeypatch.setattr(Path, "replace", failing_replace)
    artifacts = {"transcript.md": "new text", "manifest.json": "new manifest"}
    if failure:
        with pytest.raises(KeyboardInterrupt if failure == "interrupt" else OSError):
            _publish_artifacts(out, artifacts, overwrite=True)
        assert {name: (out / name).read_text() for name in originals} == originals
    else:
        _publish_artifacts(out, artifacts, overwrite=True)
        assert all((out / name).read_text() == content for name, content in artifacts.items())
        assert not (out / "transcript.srt").exists()
    assert (out / "notes/transcript.md").read_text() == "unrelated notes"
    assert (out / "link").is_symlink() and source.read_text() == "original"
    assert not list(out.glob(".transcribe-*"))


def test_failed_rollback_keeps_recoverable_backup(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "transcript.md").write_text("old")
    replace = Path.replace
    def fail(path, target):
        if path.parent.name in ("new", "previous"):
            raise OSError("rename failed")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(RunError, match="предыдущие файлы сохранены"):
        _publish_artifacts(out, {"transcript.md": "new"}, overwrite=True)
    assert next(out.glob(".transcribe-*/previous/transcript.md")).read_text() == "old"


def test_publication_preserves_cwd_and_concurrent_unrelated_edits(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "notes.txt").write_text("old notes")
    fifo = out / "pipe"
    os.mkfifo(fifo)
    directory_inode, fifo_inode = out.stat().st_ino, fifo.stat().st_ino
    monkeypatch.chdir(out)
    write = Path.write_text
    def edit_notes(path, content, *args, **kwargs):
        result = write(path, content, *args, **kwargs)
        if path.parent.name == "new" and path.name == "manifest.json":
            write(out / "notes.txt", "edited while publishing")
            write(out / "new-note.txt", "created while publishing")
        return result
    monkeypatch.setattr(Path, "write_text", edit_notes)
    _publish_artifacts(out, {"transcript.md": "new", "manifest.json": "{}"}, overwrite=True)
    assert Path.cwd() == out and out.stat().st_ino == directory_inode
    assert Path("notes.txt").read_text() == "edited while publishing"
    assert Path("new-note.txt").read_text() == "created while publishing"
    assert fifo.stat().st_ino == fifo_inode


def test_invalid_wav_and_speakers_are_run_errors(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_bytes(b"not a WAV")
    with pytest.raises(RunError, match="WAV"):
        _wav_duration(path)
    with pytest.raises(RunError, match="--speakers"):
        run(path, speakers="autp", out=tmp_path / "out")


def test_run_write_error_does_not_abort_cli_batch(monkeypatch, tmp_path, capsys):
    from transcribe.cli import main
    from transcribe.engine import FluidAudioEngine, Transcript
    source = tmp_path / "audio.wav"
    source.write_bytes(b"synthetic")
    fluid = tmp_path / "engine"
    fluid.touch()
    monkeypatch.setattr("transcribe.run.FLUID", fluid)
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/synthetic/tool")
    monkeypatch.setattr("transcribe.run._to_wav16k", lambda *args: None)
    monkeypatch.setattr("transcribe.run._wav_duration", lambda path: 1.)
    monkeypatch.setattr(FluidAudioEngine, "transcribe", lambda *args, **kwargs: Transcript(
        words=[{"start": 0, "end": 1, "text": "hello"}]))
    write = Path.write_text
    writes = []
    def fail_once(path, content, *args, **kwargs):
        writes.append(path)
        if len(writes) == 2:
            raise OSError("disk full")
        return write(path, content, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail_once)
    with pytest.raises(SystemExit) as error:
        main([str(source), str(source), "--speakers", "off", "--out-root", str(tmp_path / "results")])
    assert error.value.code == 1
    completed = list((tmp_path / "results").rglob("transcript.md"))
    assert len(completed) == 1 and "hello" in completed[0].read_text()
    assert "disk full" in capsys.readouterr().err


@pytest.mark.parametrize("url", ["https://example.org/youtube.com", "https://youtube.com.example.org/watch", "ftp://youtu.be/id"])
def test_rejects_non_youtube_hosts(monkeypatch, tmp_path, url):
    engine = tmp_path / "engine"
    engine.touch()
    monkeypatch.setattr("transcribe.run.FLUID", engine)
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/synthetic/tool")
    with pytest.raises(RunError, match="YouTube"):
        run(url, out=tmp_path / "out")


def test_overwrite_cannot_remove_source(monkeypatch, tmp_path):
    source = tmp_path / "transcript.md"
    source.write_bytes(b"synthetic media")
    engine = tmp_path / "engine"
    engine.touch()
    monkeypatch.setattr("transcribe.run.FLUID", engine)
    monkeypatch.setattr("transcribe.run.shutil.which", lambda tool: "/synthetic/tool")
    with pytest.raises(RunError, match="overwrite the source"):
        run(source, out=tmp_path, overwrite=True)
    assert source.read_bytes() == b"synthetic media"


def test_writable_output_does_not_require_writable_parent(tmp_path):
    parent = tmp_path / "read-only-parent"
    out = parent / "output"
    out.mkdir(parents=True)
    parent.chmod(0o555)
    try:
        _publish_artifacts(out, {"transcript.md": "new"}, overwrite=False)
        assert (out / "transcript.md").read_text() == "new"
        assert not list(out.glob(".transcribe-*"))
    finally:
        parent.chmod(0o755)


def test_speaker_window_matches_full_scan(monkeypatch):
    random = Random(7)
    diar = sorted([(random.uniform(0, 500), random.uniform(1, 30), f"S{i % 3}", random.random())
                   for i in range(300)])
    diar = [(start, start + duration, speaker, quality) for start, duration, speaker, quality in diar]
    words = [{"start": start, "end": start + random.uniform(.05, 3), "text": "word"}
             for start in sorted(random.uniform(0, 550) for _ in range(700))]
    checked_segments = 0
    def check(start, end, candidates, gap):
        nonlocal checked_segments
        checked_segments += len(candidates)
        result = assign_speaker(start, end, candidates, gap)
        assert result == assign_speaker(start, end, diar, gap)
        return result
    monkeypatch.setattr("transcribe.run.assign_speaker", check)
    merge_words_to_turns(words, diar)
    assert checked_segments < len(words) * len(diar) / 5


def test_subtitles_bound_length_duration_and_preserve_words():
    words = [{"start": i * .4, "end": i * .4 + .3, "text": "слово"} for i in range(150)]
    cues = merge_words_to_turns(words, [(0, 60, "S1")], max_chars=80, max_duration=6.0)
    assert all(len(c["text"]) <= 80 and c["end"] - c["start"] <= 6 for c in cues)
    assert " ".join(c["text"] for c in cues) == " ".join(w["text"] for w in words)
    srt, vtt = (_render_subtitles(cues, True, fmt) for fmt in ("srt", "vtt"))
    assert srt.startswith("1\n00:00:00,000 --> ") and "S1: слово" in srt
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> ")
    assert srt.count(" --> ") == vtt.count(" --> ") == len(cues)
