#!/usr/bin/env python3
"""Тесты модуля прогона: status()/status_line()/status_dict() на фикстурах в tmpfs."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import engine as engine_mod
import run as run_mod
from engine import EngineError, Timings, Transcript
from run import (RunError, format_duration, is_processed, load_watch_state,
                 processing_options_hash, run, save_watch_state, status,
                 status_dict, status_line, watch_candidate)


class FakeEngine:
    """Фейковый движок на шве run(): passthrough без subprocess."""

    def __init__(self, *, fail: bool = False, speakers: int = 2,
                 asr_s: float = 1.0, diar_s: float = 1.0):
        self.fail = fail
        self.speakers = speakers
        self.asr_s = asr_s
        self.diar_s = diar_s

    def transcribe(self, wav, *, lang="auto", speakers="auto", on_stage=None):
        if on_stage:
            on_stage("asr")
        if self.fail:
            raise EngineError("asr", "движок упал")
        words = [{"start": 0.0, "end": 0.5, "text": "привет"},
                 {"start": 0.6, "end": 1.0, "text": "мир"}]
        if speakers == "off":
            return Transcript(words=words, segments=[], speakers=1,
                              language="ru", text="привет мир", engine="fake",
                              timings=Timings(asr_s=self.asr_s),
                              diar_mode=None)
        if on_stage:
            on_stage("diar")
        segments = [(0.0, 0.5, "S1", 1.0), (0.6, 1.0, "S2", 1.0)]
        return Transcript(words=words, segments=segments, speakers=2,
                          language="ru", text="привет мир", engine="fake",
                          timings=Timings(asr_s=self.asr_s, diar_s=self.diar_s),
                          diar_mode="streaming")


@contextmanager
def _spy_stages():
    """Перехватывает постановки стадий в трекере: записывает их в список."""
    seen = []
    orig_set = run_mod._Tracker.set

    def spy(self, **kw):
        if "stage" in kw:
            seen.append(kw["stage"])
        return orig_set(self, **kw)

    run_mod._Tracker.set = spy
    try:
        yield seen
    finally:
        run_mod._Tracker.set = orig_set


@contextmanager
def _patch_engine(engine: FakeEngine):
    original = run_mod._ENGINE_FACTORY
    run_mod._ENGINE_FACTORY = lambda binary, model, diar_mode: engine
    try:
        yield
    finally:
        run_mod._ENGINE_FACTORY = original


@contextmanager
def _patch_prep(duration: float = 10.0):
    originals = (run_mod._ffprobe_duration, run_mod._to_wav16k)
    run_mod._ffprobe_duration = lambda path: duration
    run_mod._to_wav16k = lambda src, dst: shutil.copy(src, dst)
    try:
        yield
    finally:
        run_mod._ffprobe_duration, run_mod._to_wav16k = originals


@contextmanager
def _tmp():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def _write_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _done_state(out_dir):
    return {"status": "done", "stage": "merge", "pct": 100, "eta_s": 0,
            "elapsed_s": 310.0, "pid": 1, "source": "call.m4a",
            "speakers": 2, "duration": 754.0,
            "transcript_md": str(out_dir / "transcript.md")}


def _running_state():
    return {"status": "running", "stage": "asr", "pct": 47.0, "eta_s": 78.0,
            "elapsed_s": 150.0, "pid": 1, "source": "call.m4a"}


def test_format_duration():
    assert format_duration(754.0) == "12:34"
    assert format_duration(65.0) == "01:05"
    assert format_duration(3661.0) == "1:01:01"


def test_status_done_golden_line():
    with _tmp() as td:
        out = td / "run1"
        _write_state(out / "progress.json", _done_state(out))
        st = status(out)
        assert st.kind == "done"
        assert status_line(st) == (f"✓ готово · 2 спикер(ов) · 12:34 · elapsed 05:10"
                                   f" · {out}/transcript.md")


def test_status_running_golden_line():
    with _tmp() as td:
        out = td / "run2"
        _write_state(out / "progress.json", _running_state())
        st = status(out)
        assert st.kind == "running"
        assert status_line(st) == "🎙 ASR 47% · ETA 01:18 · elapsed 02:30 · call.m4a"


def test_status_error_golden_line():
    with _tmp() as td:
        out = td / "run3"
        _write_state(out / "progress.json",
                     {"status": "error", "error": "движок упал", "elapsed_s": 5.0})
        st = status(out)
        assert st.kind == "error"
        assert status_line(st) == "✗ ошибка: движок упал"


def test_status_idle_on_missing_file():
    with _tmp() as td:
        st = status(td / "nowhere")
        assert st.kind == "idle"
        assert status_line(st) == "нет активного прогона транскрибации"


def test_status_corrupt_file_is_degraded():
    with _tmp() as td:
        out = td / "run4"
        out.mkdir()
        (out / "progress.json").write_text("{not json")
        st = status(out)
        assert st.kind == "degraded"
        assert "повреждён" in status_line(st)
        assert status_dict(st)["status"] == "degraded"


def test_status_out_root_prefers_freshest():
    with _tmp() as td:
        old = td / "old"
        fresh = td / "fresh"
        _write_state(old / "progress.json", _done_state(old))
        time.sleep(0.01)
        _write_state(fresh / "progress.json", _running_state())
        st = status(None, out_root=td)
        assert st.out_dir == fresh


def test_status_out_dir_beats_out_root():
    with _tmp() as td:
        direct = td / "direct"
        _write_state(direct / "progress.json", _done_state(direct))
        other = td / "other"
        _write_state(other / "progress.json", _running_state())
        st = status(direct, out_root=td)
        assert st.out_dir == direct


def test_status_stale_running_is_idle():
    with _tmp() as td:
        out = td / "stale"
        _write_state(out / "progress.json", _running_state())
        past = time.time() - 300
        os.utime(out / "progress.json", (past, past))
        st = status(out, max_age_s=60.0)
        assert st.kind == "idle"


def test_status_done_never_stale():
    with _tmp() as td:
        out = td / "olddone"
        _write_state(out / "progress.json", _done_state(out))
        past = time.time() - 3600
        os.utime(out / "progress.json", (past, past))
        st = status(out)
        assert st.kind == "done"


def test_watch_candidate_requires_two_stable_observations():
    with _tmp() as td:
        source = td / "call.wav"
        source.write_bytes(b"audio")
        state = {}

        assert watch_candidate(source, state) is False
        assert watch_candidate(source, state) is True


def test_watch_candidate_rejects_hidden_temporary_and_unknown_files():
    with _tmp() as td:
        state = {}
        for name in (".hidden.wav", "copy.wav.part", "notes.txt"):
            path = td / name
            path.write_bytes(b"x")
            assert watch_candidate(path, state) is False


def test_is_processed_finds_done_manifest_for_source():
    with _tmp() as td:
        source = td / "call.wav"
        source.write_bytes(b"audio")
        output = td / "call"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps({"status": "done"}))

        assert is_processed(source, td) is True


def test_is_processed_honors_requested_options_hash():
    with _tmp() as td:
        source = td / "call.wav"
        source.write_bytes(b"audio")
        output = td / "call"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps({
            "status": "done", "options_hash": "hash-a",
            "source_path": str(source.resolve()),
        }))

        signature = run_mod.source_signature(source)
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["source_signature"] = list(signature)
        (output / "manifest.json").write_text(json.dumps(manifest))
        assert is_processed(source, td, options_hash="hash-a", signature=signature) is True
        assert is_processed(source, td, options_hash="hash-a", signature=(999, 999)) is False
        assert is_processed(source, td, options_hash="hash-b", signature=signature) is False


def test_is_processed_rejects_manifest_without_source_signature_for_watch_recovery():
    with _tmp() as td:
        source = td / "call.wav"
        source.write_bytes(b"audio")
        output = td / "call"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps({
            "status": "done", "options_hash": "hash-a",
            "source_path": str(source.resolve())}))

        assert is_processed(
            source, td, options_hash="hash-a", signature=run_mod.source_signature(source)
        ) is False


def test_is_processed_does_not_match_same_basename_from_another_directory():
    with _tmp() as td:
        first = td / "one" / "call.wav"
        second = td / "two" / "call.wav"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        output = td / "out" / "call"
        output.mkdir(parents=True)
        (output / "manifest.json").write_text(json.dumps({
            "status": "done", "options_hash": "hash-a",
            "source_path": str(first.resolve())}))

        assert is_processed(first, td / "out", options_hash="hash-a") is True
        assert is_processed(second, td / "out", options_hash="hash-a") is False


def test_watch_state_round_trips():
    with _tmp() as td:
        path = td / ".transcribe-watch.json"
        state = {"version": 1, "sources": {
            "/tmp/call.wav": {"status": "failed", "attempts": 1}}}

        save_watch_state(path, state)

        assert load_watch_state(path) == state


def test_processing_options_hash_changes_when_output_options_change():
    base = processing_options_hash(
        speakers="auto", lang="auto", diar_mode="streaming", asr_model="v3",
        clean_fillers=False, formats=(), replacements={})
    subtitle = processing_options_hash(
        speakers="auto", lang="auto", diar_mode="streaming", asr_model="v3",
        clean_fillers=False, formats=("srt",), replacements={})
    cleaned = processing_options_hash(
        speakers="auto", lang="auto", diar_mode="streaming", asr_model="v3",
        clean_fillers=True, formats=(), replacements={})

    assert len({base, subtitle, cleaned}) == 3


def test_run_writes_all_artifacts_consistently():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            res = run(str(src), out=out, speakers="auto")

        md = out / "transcript.md"
        tj = out / "transcript.json"
        mf = out / "manifest.json"
        pf = out / "progress.json"
        assert all(p.exists() for p in (md, tj, mf, pf))
        assert res.speakers == 2 and res.duration_s == 10.0
        assert res.language == "ru"

        manifest = json.loads(mf.read_text())
        tjson = json.loads(tj.read_text())
        progress = json.loads(pf.read_text())
        md_text = md.read_text()

        assert manifest["speakers"] == 2
        assert manifest["language"] == "ru"
        assert manifest["engine"] == "fake"
        assert manifest["clean_fillers"] is False
        assert manifest["source_signature"] == list(run_mod.source_signature(src))
        assert manifest["words"] == 2 and manifest["turns"] == 2
        assert len(tjson["words"]) == 2 and len(tjson["turns"]) == 2
        assert tjson["speakers"] == manifest["speakers"]
        assert "speakers: 2" in md_text
        assert "language: ru" in md_text
        assert "**[00:00 · S1]** привет" in md_text
        assert progress["status"] == "done"
        assert progress["speakers"] == 2
        assert progress["transcript_md"] == str(md)


def test_run_off_skips_diarization():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            res = run(str(src), out=out, speakers="off")

        manifest = json.loads((out / "manifest.json").read_text())
        assert res.speakers == 1
        assert manifest["diar_mode"] is None
        assert "**[00:00]** привет" in (out / "transcript.md").read_text()


def test_run_clean_fillers_keeps_raw_words_and_records_flag():
    class FillerEngine:
        def transcribe(self, wav, *, lang="auto", speakers="auto", on_stage=None):
            words = [
                {"start": 0.0, "end": 0.2, "text": "Um,"},
                {"start": 0.3, "end": 0.6, "text": "hello"},
                {"start": 0.7, "end": 0.9, "text": "uh,"},
                {"start": 1.0, "end": 1.3, "text": "world"},
            ]
            return Transcript(words=words, segments=[], speakers=1,
                              language="en", text="Um, hello uh, world",
                              engine="fake", timings=Timings(asr_s=1.0),
                              diar_mode=None)

    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FillerEngine()), _patch_prep(duration=10.0):
            run(str(src), out=out, speakers="off", clean_fillers=True)

        transcript = json.loads((out / "transcript.json").read_text())
        manifest = json.loads((out / "manifest.json").read_text())
        assert [word["text"] for word in transcript["words"]] == [
            "Um,", "hello", "uh,", "world"]
        assert transcript["turns"][0]["text"] == "hello world"
        assert manifest["clean_fillers"] is True


def test_run_writes_requested_subtitles_and_applies_replacements_to_turns_only():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        replacements = td / "terms.json"
        replacements.write_text(json.dumps({"привет": "здравствуйте"}, ensure_ascii=False))
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            result = run(str(src), out=out, speakers="auto", formats=("srt", "vtt"),
                         replacements_file=replacements)

        transcript = json.loads((out / "transcript.json").read_text())
        manifest = json.loads((out / "manifest.json").read_text())
        assert result.subtitle_paths == (out / "transcript.srt", out / "transcript.vtt")
        assert transcript["turns"][0]["text"] == "здравствуйте"
        assert transcript["words"][0]["text"] == "привет"
        assert result.options_hash == manifest["options_hash"]
        assert manifest["subtitle_formats"] == ["srt", "vtt"]
        assert manifest["replacements_file"] == str(replacements)
        assert (out / "transcript.srt").read_text() == (
            "1\n00:00:00,000 --> 00:00:00,500\nS1: здравствуйте\n\n"
            "2\n00:00:00,600 --> 00:00:01,000\nS2: мир\n"
        )
        assert (out / "transcript.vtt").read_text() == (
            "WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nS1: здравствуйте\n\n"
            "00:00:00.600 --> 00:00:01.000\nS2: мир\n"
        )


def test_run_removes_stale_subtitles_when_formats_are_not_requested():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        out.mkdir()
        (out / "transcript.srt").write_text("stale")
        (out / "transcript.vtt").write_text("stale")
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            run(str(src), out=out)

        assert not (out / "transcript.srt").exists()
        assert not (out / "transcript.vtt").exists()


def test_source_tool_failures_become_run_errors():
    original_run = run_mod.subprocess.run

    def failing_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="bad media")

    run_mod.subprocess.run = failing_run
    try:
        try:
            run_mod._to_wav16k(Path("in.wav"), Path("out.wav"))
        except RunError as exc:
            assert "ffmpeg" in str(exc)
            assert "bad media" in str(exc)
        else:
            raise AssertionError("expected RunError from ffmpeg failure")

        def missing_tool(command, **kwargs):
            raise FileNotFoundError("ffmpeg")

        run_mod.subprocess.run = missing_tool
        try:
            run_mod._to_wav16k(Path("in.wav"), Path("out.wav"))
        except RunError as exc:
            assert "ffmpeg" in str(exc)
        else:
            raise AssertionError("expected RunError from missing ffmpeg")

        run_mod.subprocess.run = failing_run
        original_which = run_mod.shutil.which
        run_mod.shutil.which = lambda tool: f"/usr/bin/{tool}"
        try:
            with _tmp() as td:
                try:
                    run_mod._fetch_youtube_audio("https://youtu.be/example", td)
                except RunError as exc:
                    assert "yt-dlp" in str(exc)
                    assert "bad media" in str(exc)
                else:
                    raise AssertionError("expected RunError from yt-dlp failure")
        finally:
            run_mod.shutil.which = original_which
    finally:
        run_mod.subprocess.run = original_run


def test_run_labels_unassigned_multi_speaker_subtitle_turns_as_unknown():
    class UnassignedSpeakerEngine:
        def transcribe(self, wav, *, lang="auto", speakers="auto", on_stage=None):
            return Transcript(
                words=[{"start": 0.0, "end": 0.5, "text": "hello"}],
                segments=[], speakers=2, language="en", text="hello",
                engine="fake", timings=Timings(asr_s=1.0), diar_mode="streaming")

    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(UnassignedSpeakerEngine()), _patch_prep(duration=10.0):
            run(str(src), out=out, formats=("srt",))

        assert "UNKNOWN: hello" in (out / "transcript.srt").read_text()


def test_run_rejects_unknown_subtitle_format_before_creating_progress():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        try:
            run(str(src), out=out, formats=("ass",))
            raise AssertionError("ожидался RunError")
        except RunError as exc:
            assert "unsupported subtitle format" in str(exc)
        assert not (out / "progress.json").exists()


def test_run_reports_invalid_utf8_replacement_file_as_run_error():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        replacements = td / "terms.json"
        replacements.write_bytes(b"{\xff")
        out = td / "out"
        try:
            run(str(src), out=out, replacements_file=replacements)
            raise AssertionError("ожидался RunError")
        except RunError as exc:
            assert "replacement dictionary" in str(exc)
        assert not (out / "progress.json").exists()


def test_run_drops_turn_when_replacement_leaves_only_whitespace():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        replacements = td / "terms.json"
        replacements.write_text(json.dumps({"привет": "   "}, ensure_ascii=False))
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            run(str(src), out=out, replacements_file=replacements)

        transcript = json.loads((out / "transcript.json").read_text())
        assert [turn["text"] for turn in transcript["turns"]] == ["мир"]


def test_run_engine_error_finalizes_progress_and_raises():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine(fail=True)), _patch_prep(duration=10.0):
            try:
                run(str(src), out=out)
                raise AssertionError("ожидался RunError")
            except RunError as exc:
                assert "движок упал" in str(exc)
        progress = json.loads((out / "progress.json").read_text())
        assert progress["status"] == "error"
        assert "движок упал" in progress["error"]


def test_run_preflight_error_leaves_no_progress():
    with _tmp() as td:
        out = td / "out"
        try:
            run(str(td / "missing.wav"), out=out)
            raise AssertionError("ожидался RunError")
        except RunError:
            pass
        assert not (out / "progress.json").exists()


def test_unexpected_error_reports_cause_in_progress():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"

        class BoomEngine(FakeEngine):
            def transcribe(self, wav, *, lang="auto", speakers="auto", on_stage=None):
                raise RuntimeError("взрыв на ровном месте")

        with _patch_engine(BoomEngine()), _patch_prep(duration=10.0):
            try:
                run(str(src), out=out)
                raise AssertionError("ожидалось исключение")
            except RuntimeError:
                pass
        progress = json.loads((out / "progress.json").read_text())
        assert progress["status"] == "error"
        assert "взрыв на ровном месте" in progress["error"]


def test_run_keep_tmp_reports_workdir():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            res = run(str(src), out=out, keep_tmp=True)
            assert res.workdir is not None and res.workdir.exists()
            res2 = run(str(src), out=out, speakers="off")
            assert res2.workdir is None


def test_manifest_timings_and_diar_mode_come_from_engine():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine(asr_s=0.5, diar_s=1.5)), _patch_prep(duration=10.0):
            run(str(src), out=out)
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["timings_s"]["asr_s"] == 0.5
        assert manifest["timings_s"]["diar_s"] == 1.5
        assert manifest["asr_rtf"] == round(10.0 / 0.5, 1)
        assert manifest["diar_mode"] == "streaming"


def test_off_manifest_diar_mode_none():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
            run(str(src), out=out, speakers="off")
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["timings_s"]["diar_s"] is None
        assert manifest["diar_mode"] is None


def test_progress_sees_all_stages():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _spy_stages() as seen:
            with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
                run(str(src), out=out)
        assert seen == ["prep", "asr", "diar", "merge"]


def test_progress_off_skips_diar_stage():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _spy_stages() as seen:
            with _patch_engine(FakeEngine()), _patch_prep(duration=10.0):
                run(str(src), out=out, speakers="off")
        assert seen == ["prep", "asr", "merge"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
