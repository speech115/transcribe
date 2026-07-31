#!/usr/bin/env python3
"""Тесты движкового шва: lib/engine.py против реальных ответов FluidAudio."""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from engine import EngineError, FluidAudioEngine

FIX = Path(__file__).parent / "fixtures" / "fluidaudio"
ASR_V3_EN = FIX / "asr_v3_en.json"
ASR_LANG_RU = FIX / "asr_lang_ru.json"
ASR_EMPTY = FIX / "asr_empty.json"
DIAR_STREAMING = FIX / "diar_streaming.json"


class FixtureRunner:
    """Тестовый адаптер на границе subprocess: кладёт ответ движка в файл."""

    def __init__(self, asr_fx: Path, diar_fx: Path):
        self.asr_fx = asr_fx
        self.diar_fx = diar_fx
        self.calls = []

    def transcribe(self, wav: Path, lang: str, model: str, out_json: Path) -> None:
        self.calls.append(("transcribe", lang, model))
        shutil.copy(self.asr_fx, out_json)

    def process(self, wav: Path, mode: str, num: int, out_json: Path) -> None:
        self.calls.append(("process", mode, num))
        shutil.copy(self.diar_fx, out_json)


def test_default_path_returns_full_transcript():
    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=FixtureRunner(ASR_V3_EN, DIAR_STREAMING))
    tr = engine.transcribe(Path("in.wav"))

    assert len(tr.words) == 39
    assert tr.words[0] == {"start": 0.88, "end": 1.28, "text": "Alright,"}
    assert len(tr.segments) == 4
    assert {s[2] for s in tr.segments} == {"S1", "S2"}
    assert tr.speakers == 2
    assert tr.language == "en"
    assert tr.engine == "fluidaudio-parakeet-v3 + pyannote-streaming"


def test_off_skips_diarization():
    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=FixtureRunner(ASR_V3_EN, DIAR_STREAMING))
    tr = engine.transcribe(Path("in.wav"), speakers="off")

    assert tr.segments == []
    assert tr.speakers == 1
    assert tr.engine == "fluidaudio-parakeet-v3"
    assert [c[0] for c in engine._runner.calls] == ["transcribe"]
    assert tr.diar_mode is None
    assert tr.timings.diar_s is None
    assert tr.timings.asr_s >= 0


def test_auto_reports_timings_and_diar_mode():
    class SlowRunner(FixtureRunner):
        def transcribe(self, wav, lang, model, out_json):
            time.sleep(0.05)
            super().transcribe(wav, lang, model, out_json)

    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=SlowRunner(ASR_V3_EN, DIAR_STREAMING))
    tr = engine.transcribe(Path("in.wav"))

    assert tr.diar_mode == "streaming"
    assert tr.timings.asr_s >= 0.04
    assert tr.timings.diar_s is not None and tr.timings.diar_s >= 0


def test_fixed_speakers_passed_to_engine():
    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=FixtureRunner(ASR_V3_EN, DIAR_STREAMING))
    tr = engine.transcribe(Path("in.wav"), speakers="2")

    assert tr.speakers == 2
    assert ("process", "streaming", 2) in engine._runner.calls
    assert tr.engine == "fluidaudio-parakeet-v3 + pyannote-streaming"


def test_forced_language_wins():
    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=FixtureRunner(ASR_V3_EN, DIAR_STREAMING))
    tr = engine.transcribe(Path("in.wav"), lang="ru")

    assert tr.language == "ru"
    assert ("transcribe", "ru", "v3") in engine._runner.calls


def test_engine_language_used_when_present():
    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=FixtureRunner(ASR_LANG_RU, DIAR_STREAMING))
    tr = engine.transcribe(Path("in.wav"))

    assert tr.language == "ru"
    assert tr.words[0]["text"] == "Привет,"


def test_empty_asr_raises_engine_error():
    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=FixtureRunner(ASR_EMPTY, DIAR_STREAMING))
    try:
        engine.transcribe(Path("in.wav"))
        raise AssertionError("ожидался EngineError")
    except EngineError as exc:
        assert exc.stage == "asr"


def test_garbage_engine_response_raises_parse_error():
    class GarbageRunner:
        def transcribe(self, wav, lang, model, out_json):
            out_json.write_text("{not json")

        def process(self, wav, mode, num, out_json):
            raise AssertionError("не должен дойти до диаризации")

    engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"),
                              runner=GarbageRunner())
    try:
        engine.transcribe(Path("in.wav"))
        raise AssertionError("ожидался EngineError")
    except EngineError as exc:
        assert exc.stage == "parse"


def _patch_subprocess_run():
    """Подмена subprocess.run на границе: записывает cmd и кладёт фикстуру в out-файл."""
    import subprocess

    calls = []
    original = subprocess.run

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out_key = "--output-json" if "transcribe" in cmd else "--output"
        out_path = Path(cmd[cmd.index(out_key) + 1])
        src = ASR_V3_EN if "transcribe" in cmd else DIAR_STREAMING
        shutil.copy(src, out_path)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    subprocess.run = fake_run
    return calls, lambda: setattr(subprocess, "run", original)


def test_golden_argv_pinned():
    calls, restore = _patch_subprocess_run()
    try:
        engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"), model="v2", diar_mode="offline")
        engine.transcribe(Path("in.wav"), lang="ru", speakers="3")
    finally:
        restore()

    asr_cmd = calls[0]
    assert asr_cmd[:4] == [str(Path("vendor/fluidaudiocli")), "transcribe", "in.wav", "--word-timestamps"]
    assert "--model-version" in asr_cmd and asr_cmd[asr_cmd.index("--model-version") + 1] == "v2"
    assert "--language" in asr_cmd and asr_cmd[asr_cmd.index("--language") + 1] == "ru"
    assert "--output-json" in asr_cmd

    diar_cmd = calls[1]
    assert diar_cmd[:3] == [str(Path("vendor/fluidaudiocli")), "process", "in.wav"]
    assert "--mode" in diar_cmd and diar_cmd[diar_cmd.index("--mode") + 1] == "offline"
    assert "--num-speakers" in diar_cmd and diar_cmd[diar_cmd.index("--num-speakers") + 1] == "3"
    assert "--num-clusters" not in diar_cmd


def test_golden_argv_auto_lang_and_streaming_clusters():
    calls, restore = _patch_subprocess_run()
    try:
        engine = FluidAudioEngine(binary=Path("vendor/fluidaudiocli"))
        engine.transcribe(Path("in.wav"), lang="auto", speakers="auto")
    finally:
        restore()

    assert "--language" not in calls[0]
    diar_cmd = calls[1]
    assert "--num-clusters" not in diar_cmd and "--num-speakers" not in diar_cmd


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
