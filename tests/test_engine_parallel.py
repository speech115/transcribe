import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from transcribe.engine import EngineError, FluidAudioEngine


def _engine_script(tmp_path):
    binary = tmp_path / "engine"
    binary.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys, time
from pathlib import Path
root = Path(__file__).parent
stage = sys.argv[1]
(root / (stage + ".pid")).write_text(str(os.getpid()))
other = "process" if stage == "transcribe" else "transcribe"
deadline = time.monotonic() + 5
while not (root / (other + ".pid")).exists():
    if time.monotonic() > deadline:
        sys.exit("ASR and diarization did not overlap")
    time.sleep(0.01)
if Path(sys.argv[2]).stem == "asr-error":
    if stage == "transcribe":
        sys.exit("ASR failed")
    time.sleep(5)
    (root / "diar-finished").touch()
if Path(sys.argv[2]).stem == "interrupt":
    time.sleep(30)
if stage == "transcribe":
    result = {"wordTimings": [{"startTime": 0, "endTime": 1, "word": "hello"}]}
    output_flag = "--output-json"
else:
    result = {"segments": [
        {"startTimeSeconds": 0, "endTimeSeconds": 0.5, "speakerId": "alice"},
        {"startTimeSeconds": 0.5, "endTimeSeconds": 1, "speakerId": "bob"}]}
    output_flag = "--output"
Path(sys.argv[sys.argv.index(output_flag) + 1]).write_text(json.dumps(result))
''')
    binary.chmod(0o700)
    return binary


def test_asr_and_streaming_diarization_overlap(tmp_path):
    result = FluidAudioEngine(binary=_engine_script(tmp_path)).transcribe(tmp_path / "audio.wav")
    assert result.words == [{"start": 0, "end": 1, "text": "hello"}]
    assert result.speakers == 2 and result.diar_status == "success"
    assert result.asr_s > 0 and result.diar_s > 0


def test_asr_failure_stops_diarization_and_cleans_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    engine = FluidAudioEngine(binary=_engine_script(tmp_path))
    with pytest.raises(EngineError, match="ASR failed"):
        engine.transcribe(tmp_path / "asr-error.wav")
    assert not (tmp_path / "diar-finished").exists()
    assert not list(tmp_path.glob("engine_*.json"))
    for path in tmp_path.glob("*.pid"):
        with pytest.raises(ProcessLookupError):
            os.kill(int(path.read_text()), 0)


def test_interrupt_reaps_both_processes_and_removes_temporary_files(tmp_path):
    binary = _engine_script(tmp_path)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; "
            "from transcribe.engine import FluidAudioEngine; "
            "FluidAudioEngine(binary=Path(sys.argv[2])).transcribe(Path(sys.argv[3]))")
    source = str(Path(__file__).resolve().parents[1] / "src")
    with subprocess.Popen([sys.executable, "-c", code, source, str(binary), str(tmp_path / "interrupt.wav")],
                          env={**os.environ, "TMPDIR": str(tmp_path)},
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True) as driver:
        try:
            deadline = time.monotonic() + 5
            while len(list(tmp_path.glob("*.pid"))) < 2:
                assert time.monotonic() < deadline, "both stages must start before interruption"
                time.sleep(0.01)
            driver.send_signal(signal.SIGINT)
            _, stderr = driver.communicate(timeout=5)
            assert driver.returncode != 0 and "KeyboardInterrupt" in stderr
            assert not list(tmp_path.glob("engine_*.json"))
            for path in tmp_path.glob("*.pid"):
                with pytest.raises(ProcessLookupError):
                    os.kill(int(path.read_text()), 0)
        finally:
            if driver.poll() is None:
                driver.kill()
                driver.wait()
            for path in tmp_path.glob("*.pid"):
                try:
                    os.kill(int(path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
