#!/usr/bin/env python3
"""Transcribe audio (optionally with speaker diarization) using API backends."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import uuid
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

DEFAULT_BACKEND = "openai"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_OPENAI_DIARIZE_MODEL = "gpt-4o-transcribe-diarize"
DEFAULT_DEEPGRAM_MODEL = "nova-3"
DEFAULT_RESPONSE_FORMAT = "text"
DEFAULT_CHUNKING_STRATEGY = "auto"
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_KNOWN_SPEAKERS = 4

ALLOWED_RESPONSE_FORMATS = {"text", "json", "diarized_json"}
ALLOWED_BACKENDS = {"openai", "deepgram"}


def _die(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def _ensure_api_key(backend: str, dry_run: bool) -> None:
    env_name = "OPENAI_API_KEY" if backend == "openai" else "DEEPGRAM_API_KEY"
    if os.getenv(env_name):
        print(f"{env_name} is set.", file=sys.stderr)
        return
    if dry_run:
        _warn(f"{env_name} is not set; dry-run only.")
        return
    _die(f"{env_name} is not set. Export it before running.")


def _normalize_backend(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_BACKEND
    backend = value.strip().lower()
    if backend not in ALLOWED_BACKENDS:
        _die("backend must be one of: " + ", ".join(sorted(ALLOWED_BACKENDS)))
    return backend


def _normalize_response_format(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_RESPONSE_FORMAT
    fmt = value.strip().lower()
    if fmt not in ALLOWED_RESPONSE_FORMATS:
        _die(
            "response-format must be one of: "
            + ", ".join(sorted(ALLOWED_RESPONSE_FORMATS))
        )
    return fmt


def _normalize_chunking_strategy(value: Optional[str]) -> Any:
    if not value:
        return DEFAULT_CHUNKING_STRATEGY
    raw = str(value).strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            _die("chunking-strategy JSON is invalid")
    return raw


def _normalize_model(backend: str, model: Optional[str], response_format: str) -> str:
    if model and model.strip():
        return model.strip()
    if backend == "deepgram":
        return DEFAULT_DEEPGRAM_MODEL
    if response_format == "diarized_json":
        return DEFAULT_OPENAI_DIARIZE_MODEL
    return DEFAULT_OPENAI_MODEL


def _guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    return "audio/wav"


def _encode_data_url(path: Path) -> str:
    data = path.read_bytes()
    mime = _guess_mime_type(path)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _parse_known_speakers(raw_items: List[str]) -> Tuple[List[str], List[str]]:
    names: List[str] = []
    refs: List[str] = []
    for raw in raw_items:
        if "=" not in raw:
            _die("known-speaker must be NAME=PATH")
        name, path_str = raw.split("=", 1)
        name = name.strip()
        path = Path(path_str.strip())
        if not name or not path_str.strip():
            _die("known-speaker must be NAME=PATH")
        if not path.exists():
            _die(f"Known speaker file not found: {path}")
        names.append(name)
        refs.append(_encode_data_url(path))
    if len(names) > MAX_KNOWN_SPEAKERS:
        _die(f"known speakers must be <= {MAX_KNOWN_SPEAKERS}")
    return names, refs


def _output_extension(response_format: str) -> str:
    return "txt" if response_format == "text" else "json"


def _build_output_path(
    audio_path: Path,
    response_format: str,
    out: Optional[str],
    out_dir: Optional[str],
) -> Path:
    ext = "." + _output_extension(response_format)
    if out:
        path = Path(out)
        if path.exists() and path.is_dir():
            return path / f"{audio_path.stem}.transcript{ext}"
        if path.suffix == "":
            return path.with_suffix(ext)
        return path
    if out_dir:
        base = Path(out_dir)
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{audio_path.stem}.transcript{ext}"
    return Path(f"{audio_path.stem}.transcript{ext}")


def _create_openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI()


def _format_output(result: Any, response_format: str, backend: str) -> str:
    if backend == "deepgram":
        if response_format == "text":
            return _deepgram_text(result)
        return json.dumps(result, indent=2, ensure_ascii=False)
    if response_format == "text":
        if isinstance(result, dict):
            text = result.get("text")
            if isinstance(text, str):
                return text
        text = getattr(result, "text", None)
        return text if isinstance(text, str) else str(result)
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), indent=2)
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return json.dumps({"text": getattr(result, "text", str(result))}, indent=2)


def _deepgram_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)
    results = result.get("results") or {}
    channels = results.get("channels") or []
    if channels:
        alternatives = channels[0].get("alternatives") or []
        if alternatives:
            transcript = alternatives[0].get("transcript")
            if isinstance(transcript, str):
                return transcript
    transcript = result.get("transcript")
    if isinstance(transcript, str):
        return transcript
    return json.dumps(result, ensure_ascii=False)


def _validate_audio(path: Path, backend: str) -> None:
    if not path.exists():
        _die(f"Audio file not found: {path}")
    size = path.stat().st_size
    if backend == "openai" and size > MAX_AUDIO_BYTES:
        _warn(
            f"Audio file exceeds 25MB limit ({size} bytes): {path}"
        )


def _build_openai_payload(
    args: argparse.Namespace,
    known_speaker_names: List[str],
    known_speaker_refs: List[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": args.model,
        "response_format": args.response_format,
        "chunking_strategy": args.chunking_strategy,
    }
    if args.language:
        payload["language"] = args.language
    if args.prompt:
        payload["prompt"] = args.prompt
    if known_speaker_names:
        payload["extra_body"] = {
            "known_speaker_names": known_speaker_names,
            "known_speaker_references": known_speaker_refs,
        }
    return payload


def _run_one_openai(
    client: Any,
    audio_path: Path,
    payload: Dict[str, Any],
) -> Any:
    with audio_path.open("rb") as audio_file:
        return client.audio.transcriptions.create(
            file=audio_file,
            **payload,
        )


def _multipart_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _encode_multipart_request(audio_path: Path, payload: Dict[str, Any]) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    filtered_payload = {key: value for key, value in payload.items() if value is not None and key != "extra_body"}
    if payload.get("extra_body"):
        _warn("openai SDK not installed; extra_body fields are ignored in HTTP fallback mode.")

    for key, value in filtered_payload.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n{_multipart_value(value)}\r\n'.encode("utf-8")
        )

    filename = audio_path.name
    mime_type = _guess_mime_type(audio_path)
    file_bytes = audio_path.read_bytes()
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def _run_one_openai_http(audio_path: Path, payload: Dict[str, Any]) -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _die("OPENAI_API_KEY is not set. Export it before running.")

    body, boundary = _encode_multipart_request(audio_path, payload)
    request = urllib_request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:  # pragma: no cover - exercised in live runs
        detail = exc.read().decode("utf-8", errors="replace")
        _die(f"OpenAI API request failed ({exc.code}): {detail}")
    except urllib_error.URLError as exc:  # pragma: no cover - exercised in live runs
        _die(f"OpenAI API request failed: {exc.reason}")

    response_format = str(payload.get("response_format") or "text")
    if response_format == "text":
        return {"text": raw}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        _die(f"OpenAI API returned invalid JSON: {exc}")


def _deepgram_query_args(args: argparse.Namespace) -> dict[str, str]:
    query: dict[str, str] = {
        "model": args.model,
        "smart_format": "true",
        "punctuate": "true",
    }
    if args.language:
        query["language"] = args.language
    else:
        query["detect_language"] = "true"
    if args.response_format in {"json", "diarized_json"}:
        query["utterances"] = "true"
    if args.response_format == "diarized_json":
        query["diarize"] = "true"
    return query


def _run_one_deepgram(audio_path: Path, args: argparse.Namespace) -> Any:
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        _die("DEEPGRAM_API_KEY is not set. Export it before running.")

    query = urllib_parse.urlencode(_deepgram_query_args(args))
    url = f"https://api.deepgram.com/v1/listen?{query}"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": _guess_mime_type(audio_path),
    }
    request = urllib_request.Request(
        url,
        data=audio_path.read_bytes(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib_request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:  # pragma: no cover - exercised in live runs
        detail = exc.read().decode("utf-8", errors="replace")
        _die(f"Deepgram API request failed ({exc.code}): {detail}")
    except urllib_error.URLError as exc:  # pragma: no cover - exercised in live runs
        _die(f"Deepgram API request failed: {exc.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe audio (optionally with speaker diarization) using OpenAI."
    )
    parser.add_argument("audio", nargs="+", help="Audio file(s) to transcribe")
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND,
        help="Backend to use: openai or deepgram",
    )
    parser.add_argument(
        "--model",
        help="Model to use. Defaults depend on backend/response format.",
    )
    parser.add_argument(
        "--response-format",
        default=DEFAULT_RESPONSE_FORMAT,
        help="Response format: text, json, or diarized_json",
    )
    parser.add_argument(
        "--chunking-strategy",
        default=DEFAULT_CHUNKING_STRATEGY,
        help="Chunking strategy (use 'auto' for long audio)",
    )
    parser.add_argument("--language", help="Optional language hint (e.g. 'en')")
    parser.add_argument("--prompt", help="Optional prompt to guide transcription")
    parser.add_argument(
        "--known-speaker",
        action="append",
        default=[],
        help="Known speaker reference as NAME=PATH (repeatable, max 4)",
    )
    parser.add_argument("--out", help="Output file path (single audio only)")
    parser.add_argument("--out-dir", help="Output directory for transcripts")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write transcript to stdout instead of a file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print payload without calling the API",
    )

    args = parser.parse_args()
    args.backend = _normalize_backend(args.backend)
    args.response_format = _normalize_response_format(args.response_format)
    args.chunking_strategy = _normalize_chunking_strategy(args.chunking_strategy)
    args.model = _normalize_model(args.backend, args.model, args.response_format)

    if args.out and len(args.audio) > 1:
        _die("--out only supports a single audio file")
    if args.stdout and (args.out or args.out_dir):
        _die("--stdout cannot be combined with --out or --out-dir")
    if args.stdout and len(args.audio) > 1:
        _die("--stdout only supports a single audio file")

    if args.backend == "deepgram" and args.prompt:
        _die("prompt is not supported with the Deepgram backend")
    if args.prompt and "transcribe-diarize" in args.model:
        _die("prompt is not supported with gpt-4o-transcribe-diarize")
    if (
        args.backend == "openai"
        and args.response_format == "diarized_json"
        and "transcribe-diarize" not in args.model
    ):
        _die("diarized_json requires gpt-4o-transcribe-diarize")

    _ensure_api_key(args.backend, args.dry_run)

    audio_paths = [Path(p) for p in args.audio]
    for path in audio_paths:
        _validate_audio(path, args.backend)

    known_names, known_refs = _parse_known_speakers(args.known_speaker)
    if args.backend == "deepgram" and known_names:
        _warn("known-speaker references are not supported with Deepgram; ignoring.")
        known_names = []
        known_refs = []
    if args.backend == "openai" and known_names and "transcribe-diarize" not in args.model:
        _warn("known-speaker references are only supported for gpt-4o-transcribe-diarize")
    payload = _build_openai_payload(args, known_names, known_refs) if args.backend == "openai" else _deepgram_query_args(args)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    client = _create_openai_client() if args.backend == "openai" else None

    for path in audio_paths:
        if args.backend == "openai":
            if client is not None:
                result = _run_one_openai(client, path, payload)
            else:
                result = _run_one_openai_http(path, payload)
        else:
            result = _run_one_deepgram(path, args)
        output = _format_output(result, args.response_format, args.backend)
        if args.stdout:
            print(output)
            continue
        out_path = _build_output_path(path, args.response_format, args.out, args.out_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
