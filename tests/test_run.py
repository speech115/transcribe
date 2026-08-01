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
from run import (RunError, format_duration, is_processed, run, status, status_dict,
                 status_line, watch_candidate)


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
def _patch_source_seam(fake):
    """Replace the source-preparation seam for run-lifecycle tests."""
    original = run_mod._prepare_source
    run_mod._prepare_source = fake
    try:
        yield
    finally:
        run_mod._prepare_source = original


@contextmanager
def _patch_prepare(duration: float = 10.0):
    """Use one fake source-preparation seam instead of three old patches."""
    def fake(source, *, out, out_root, workdir, on_out_dir=None, on_src_duration=None):
        out_dir = Path(out) if out is not None else Path(out_root) / "fake"
        if on_out_dir is not None:
            on_out_dir(out_dir)
        if on_src_duration is not None:
            on_src_duration(duration)
        wav = Path(workdir) / "audio_16k.wav"
        wav.write_bytes(b"x" * 100)
        return run_mod.PreparedSource(out_dir=out_dir, wav=wav, duration=duration,
                                      source_label=Path(source).name, prep_s=1.0)

    with _patch_source_seam(fake):
        yield


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


def test_run_writes_all_artifacts_consistently():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine()), _patch_prepare(duration=10.0):
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
        assert manifest["status"] == "done"
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
        with _patch_engine(FakeEngine()), _patch_prepare(duration=10.0):
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
        with _patch_engine(FillerEngine()), _patch_prepare(duration=10.0):
            run(str(src), out=out, speakers="off", clean_fillers=True)

        transcript = json.loads((out / "transcript.json").read_text())
        manifest = json.loads((out / "manifest.json").read_text())
        assert [word["text"] for word in transcript["words"]] == [
            "Um,", "hello", "uh,", "world"]
        assert transcript["turns"][0]["text"] == "hello world"
        assert manifest["clean_fillers"] is True


def test_run_engine_error_finalizes_progress_and_raises():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine(fail=True)), _patch_prepare(duration=10.0):
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

        with _patch_engine(BoomEngine()), _patch_prepare(duration=10.0):
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
        with _patch_engine(FakeEngine()), _patch_prepare(duration=10.0):
            res = run(str(src), out=out, keep_tmp=True)
            assert res.workdir is not None and res.workdir.exists()
            res2 = run(str(src), out=out, speakers="off")
            assert res2.workdir is None


def test_prep_error_after_tracker_finalizes_progress_and_raises():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"

        def failing(input, *, out, out_root, workdir, on_out_dir=None, on_src_duration=None):
            if on_out_dir is not None:
                on_out_dir(Path(out) if out is not None else Path(out_root) / "fake")
            raise RunError("ffmpeg не смог сконвертировать аудио: битый файл")

        with _patch_source_seam(failing), _patch_engine(FakeEngine()):
            try:
                run(str(src), out=out)
                raise AssertionError("ожидался RunError")
            except RunError as exc:
                assert "ffmpeg" in str(exc)

        progress = json.loads((out / "progress.json").read_text())
        assert progress["status"] == "error"
        assert "ffmpeg" in progress["error"]


def test_prep_error_before_tracker_leaves_no_progress():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"

        def failing(input, *, out, out_root, workdir, on_out_dir=None, on_src_duration=None):
            raise RunError("файл не найден")

        with _patch_source_seam(failing), _patch_engine(FakeEngine()):
            try:
                run(str(src), out=out)
                raise AssertionError("ожидался RunError")
            except RunError as exc:
                assert "файл не найден" in str(exc)

        assert not (out / "progress.json").exists()


def test_engine_error_before_tracker_is_run_error_without_progress():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"

        def failing(input, *, out, out_root, workdir, on_out_dir=None, on_src_duration=None):
            raise EngineError("prep", "engine seam failed")

        with _patch_source_seam(failing), _patch_engine(FakeEngine()):
            try:
                run(str(src), out=out)
                raise AssertionError("ожидался RunError")
            except RunError as exc:
                assert "engine seam failed" in str(exc)

        assert not (out / "progress.json").exists()


def test_progress_file_exists_before_fetch():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        observed = {}

        def spy(input, *, out, out_root, workdir, on_out_dir=None, on_src_duration=None):
            out_dir = Path(out) if out is not None else Path(out_root) / "fake"
            if on_out_dir is not None:
                on_out_dir(out_dir)
            progress = out_dir / "progress.json"
            observed["exists_before_fetch"] = progress.exists()
            if progress.exists():
                observed["stage_before_fetch"] = json.loads(progress.read_text())["stage"]
            wav = Path(workdir) / "audio_16k.wav"
            wav.write_bytes(b"x" * 100)
            return run_mod.PreparedSource(out_dir=out_dir, wav=wav, duration=10.0,
                                          source_label=Path(input).name, prep_s=1.0)

        with _patch_source_seam(spy), _patch_engine(FakeEngine()):
            run(str(src), out=out)

        assert observed["exists_before_fetch"] is True
        assert observed["stage_before_fetch"] == "prep"


def test_manifest_timings_and_diar_mode_come_from_engine():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _patch_engine(FakeEngine(asr_s=0.5, diar_s=1.5)), _patch_prepare(duration=10.0):
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
        with _patch_engine(FakeEngine()), _patch_prepare(duration=10.0):
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
            with _patch_engine(FakeEngine()), _patch_prepare(duration=10.0):
                run(str(src), out=out)
        assert seen == ["prep", "asr", "diar", "merge"]


def test_progress_off_skips_diar_stage():
    with _tmp() as td:
        src = td / "in.wav"
        src.write_bytes(b"x" * 100)
        out = td / "out"
        with _spy_stages() as seen:
            with _patch_engine(FakeEngine()), _patch_prepare(duration=10.0):
                run(str(src), out=out, speakers="off")
        assert seen == ["prep", "asr", "merge"]


# ---------------------------------------------------------------------------
# Source-preparation seam (_prepare_source)
# ---------------------------------------------------------------------------

class _FakeSubprocess:
    """Fake subprocess.run that writes artifacts and returns responses."""

    def __init__(self, ffprobe="12.5\n", title="Классное видео\n"):
        self.calls = []
        self.ffprobe = ffprobe
        self.title = title
        self.fail_ffmpeg = False
        self.fail_ffmpeg_oserror = False
        self.fail_ytdlp = False
        self.fail_ytdlp_oserror = False
        self.fail_title_oserror = False
        self.fail_probe = False

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "yt-dlp":
            if "--skip-download" in cmd and self.fail_title_oserror:
                raise OSError("yt-dlp unavailable")
            if self.fail_ytdlp:
                raise subprocess.CalledProcessError(1, cmd, stderr="Unable to download")
            if self.fail_ytdlp_oserror:
                raise OSError("download failed")
            if "--skip-download" in cmd:
                return subprocess.CompletedProcess(cmd, 0, self.title, "")
            tmpl = cmd[cmd.index("-o") + 1]
            (Path(tmpl).parent / "yt_audio.m4a").write_bytes(b"x")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "ffprobe":
            if self.fail_probe:
                raise subprocess.CalledProcessError(1, cmd, stderr="Invalid data found")
            return subprocess.CompletedProcess(cmd, 0, self.ffprobe, "")
        if cmd[0] == "ffmpeg":
            if self.fail_ffmpeg:
                raise subprocess.CalledProcessError(1, cmd, stderr="invalid data")
            if self.fail_ffmpeg_oserror:
                raise OSError("ffmpeg unavailable")
            Path(cmd[-1]).write_bytes(b"x")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")


@contextmanager
def _patch_subprocess(fake):
    original = subprocess.run
    subprocess.run = fake
    try:
        yield
    finally:
        subprocess.run = original


@contextmanager
def _patch_tools(overrides: dict | None = None):
    overrides = overrides or {}
    original = shutil.which

    def fake(name, *args, **kwargs):
        if name in overrides:
            return overrides[name]
        return True

    run_mod.shutil.which = fake
    try:
        yield
    finally:
        run_mod.shutil.which = original


def _run_with_real_prepare(source, fake, *, out=None, out_root=None,
                           keep_tmp=False, time_values=None,
                           tool_overrides=None):
    """Run through the public seam while replacing external tools."""
    original_time = run_mod.time.time
    if time_values is not None:
        values = iter(time_values)
        last = time_values[-1]

        def fake_time():
            nonlocal last
            try:
                last = next(values)
            except StopIteration:
                pass
            return last

        run_mod.time.time = fake_time
    try:
        with (_patch_subprocess(fake), _patch_tools(tool_overrides),
              _patch_engine(FakeEngine())):
            return run(str(source), out=out, out_root=out_root,
                       speakers="off", keep_tmp=keep_tmp)
    finally:
        run_mod.time.time = original_time


def test_prepare_source_local_pins_commands():
    with _tmp() as td:
        src = td / "in.m4a"
        src.write_bytes(b"x")
        out = td / "out"
        fake = _FakeSubprocess()
        result = _run_with_real_prepare(src, fake, out=out, keep_tmp=True)
        try:
            assert result.out_dir == out
            assert result.duration_s == 12.5
            assert json.loads(result.manifest.read_text())["source"] == "in.m4a"
            assert fake.calls[0][0] == "ffprobe" and fake.calls[0][-1] == str(src)
            ffmpeg = fake.calls[1]
            assert ffmpeg[:6] == ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
            assert ffmpeg[-5:-1] == ["-ar", "16000", "-ac", "1"]
            probe = fake.calls[2]
            assert probe[0] == "ffprobe" and probe[-1] == str(result.workdir / "audio_16k.wav")
        finally:
            shutil.rmtree(result.workdir, ignore_errors=True)


def test_prepare_source_youtube_names_folder_and_fetches():
    with _tmp() as td:
        root = td / "root"
        fake = _FakeSubprocess()
        result = _run_with_real_prepare(
            "https://youtu.be/abc123", fake, out_root=root, keep_tmp=True)
        try:
            assert result.out_dir == root / "Классное видео"
            assert json.loads(result.manifest.read_text())["source"] == "https://youtu.be/abc123"
            assert result.workdir.joinpath("yt_audio.m4a").exists()
            title_cmd, fetch_cmd = fake.calls[0], fake.calls[1]
            assert title_cmd[0] == "yt-dlp" and "--skip-download" in title_cmd
            assert fetch_cmd[:3] == ["yt-dlp", "-f", "bestaudio"]
        finally:
            shutil.rmtree(result.workdir, ignore_errors=True)


def test_prepare_source_empty_youtube_title_falls_back():
    with _tmp() as td:
        root = td / "root"
        fake = _FakeSubprocess(title="\n")
        result = _run_with_real_prepare(
            "https://youtu.be/abc", fake, out_root=root)
        assert result.out_dir == root / "youtube"


def test_prepare_source_local_names_folder_from_stem():
    with _tmp() as td:
        src = td / "in.m4a"
        src.write_bytes(b"x")
        root = td / "root"
        fake = _FakeSubprocess()
        result = _run_with_real_prepare(src, fake, out_root=root)
        assert result.out_dir == root / "in"
        assert json.loads(result.manifest.read_text())["source"] == "in.m4a"


def test_prepare_source_unique_dir_on_collision():
    with _tmp() as td:
        root = td / "root"
        (root / "Классное видео").mkdir(parents=True)
        fake = _FakeSubprocess()
        result = _run_with_real_prepare(
            "https://youtu.be/abc123", fake, out_root=root)
        assert result.out_dir == root / "Классное видео-2"


def test_prepare_source_errors_are_run_errors():
    with _tmp() as td:
        cases = [
            (str(td / "missing.m4a"), "файл не найден"),
            ("https://example.com/x", "YouTube"),
            ("https://notyoutube.com/watch?v=x", "YouTube"),
        ]
        for src, msg in cases:
            try:
                _run_with_real_prepare(src, _FakeSubprocess(), out=td / "o")
                raise AssertionError(f"expected RunError: {src}")
            except RunError as exc:
                assert msg in str(exc)

        try:
            _run_with_real_prepare("https://youtu.be/abc", _FakeSubprocess(),
                                   out=td / "o2", tool_overrides={"yt-dlp": None})
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "yt-dlp" in str(exc)


def test_prepare_source_ffmpeg_failure_is_run_error():
    with _tmp() as td:
        src = td / "in.m4a"
        src.write_bytes(b"x")
        fake = _FakeSubprocess()
        fake.fail_ffmpeg = True
        try:
            _run_with_real_prepare(src, fake, out=td / "o")
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "ffmpeg" in str(exc)


def test_prepare_source_ytdlp_failure_is_run_error():
    with _tmp() as td:
        fake = _FakeSubprocess()
        fake.fail_ytdlp = True
        try:
            _run_with_real_prepare("https://youtu.be/abc", fake, out=td / "o")
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "yt-dlp" in str(exc)


def test_prepare_source_oserror_is_run_error():
    with _tmp() as td:
        src = td / "in.m4a"
        src.write_bytes(b"x")

        fake = _FakeSubprocess()
        fake.fail_title_oserror = True
        try:
            _run_with_real_prepare("https://youtu.be/abc", fake, out_root=td / "root")
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "название" in str(exc)

        fake = _FakeSubprocess()
        fake.fail_ytdlp_oserror = True
        try:
            _run_with_real_prepare("https://youtu.be/abc", fake, out=td / "o")
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "yt-dlp" in str(exc)

        fake = _FakeSubprocess()
        fake.fail_ffmpeg_oserror = True
        try:
            _run_with_real_prepare(src, fake, out=td / "o")
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "ffmpeg" in str(exc)


def test_prepare_source_prep_time_includes_youtube_fetch():
    with _tmp() as td:
        fake = _FakeSubprocess()
        result = _run_with_real_prepare(
            "https://youtu.be/abc", fake, out=td / "o",
            time_values=[100.0, 100.0, 204.25, 204.25])
        manifest = json.loads(result.manifest.read_text())
        assert manifest["timings_s"]["prep_s"] == 104.2


def test_prepare_source_probe_failure_is_run_error():
    with _tmp() as td:
        src = td / "in.m4a"
        src.write_bytes(b"x")
        fake = _FakeSubprocess()
        fake.fail_probe = True
        try:
            _run_with_real_prepare(src, fake, out=td / "o")
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "ffprobe" in str(exc)


def test_failed_explicit_output_removes_stale_manifest():
    with _tmp() as td:
        src = td / "in.m4a"
        src.write_bytes(b"x")
        out = td / "out"
        out.mkdir()
        (out / "manifest.json").write_text('{"source": "old"}')
        fake = _FakeSubprocess()
        fake.fail_ffmpeg = True

        try:
            _run_with_real_prepare(src, fake, out=out)
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "ffmpeg" in str(exc)

        assert not (out / "manifest.json").exists()
        assert json.loads((out / "progress.json").read_text())["status"] == "error"


def test_early_explicit_output_failure_clears_old_markers():
    with _tmp() as td:
        src = td / "missing.m4a"
        out = td / "out"
        out.mkdir()
        (out / "manifest.json").write_text('{"source": "old"}')
        (out / "progress.json").write_text('{"status": "done"}')

        try:
            _run_with_real_prepare(src, _FakeSubprocess(), out=out)
            raise AssertionError("expected RunError")
        except RunError as exc:
            assert "файл не найден" in str(exc)

        assert not (out / "manifest.json").exists()
        assert not (out / "progress.json").exists()


# ---------------------------------------------------------------------------
# Manifest model (manifest.json schema)
# ---------------------------------------------------------------------------

def _sample_manifest():
    return run_mod.Manifest(source="call.m4a", duration=754.0, speakers=2,
                            language="ru", engine="fake",
                            generated="2026-08-01T00:00:00Z",
                            out_dir="/tmp/out",
                            timings_s={"prep_s": 1.0, "asr_s": 12.5, "diar_s": 3.0},
                            asr_rtf=60.3, asr_model="v3", diar_mode="streaming",
                            speakers_arg="auto", words=1200, turns=100,
                            engine_binary="/usr/bin/fake")


def test_manifest_roundtrip():
    m = _sample_manifest()
    assert run_mod.Manifest.from_dict(m.to_dict()) == m
    d = m.to_dict()
    assert d["diar_mode"] == "streaming"
    assert d["asr_rtf"] == 60.3


def test_manifest_from_dict_missing_keys_stay_none():
    m = run_mod.Manifest.from_dict({"source": "x", "duration": 10.0})
    assert m.speakers is None and m.diar_mode is None and m.timings_s is None


def test_corpus_row_missing_keys_are_null():
    row = run_mod.Manifest.from_dict({"source": "x"}).to_corpus_row(Path("/m/manifest.json"))
    assert row["language"] is None and row["prep_s"] is None
    assert row["source"] == "x"


def test_corpus_row_projection():
    row = _sample_manifest().to_corpus_row(Path("/x/manifest.json"))
    assert row["source"] == "call.m4a"
    assert row["prep_s"] == 1.0 and row["asr_s"] == 12.5 and row["diar_s"] == 3.0
    assert row["measured_rtf"] == round(754.0 / 12.5, 2)
    assert row["manifest_path"] == "/x/manifest.json"
    assert "timings_s" not in row
    assert list(row)[:6] == ["source", "duration", "speakers", "language",
                             "engine", "generated"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
