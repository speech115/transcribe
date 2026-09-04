#!/usr/bin/env python3
"""Local offline transcription CLI."""
import argparse
import sys
from pathlib import Path

from .run import DEFAULT_OUT_ROOT, RunError, format_duration, normalize_formats, run


def _parse_formats(value: str) -> tuple[str, ...]:
    try:
        return normalize_formats(value)
    except RunError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _print_result(result) -> None:
    print(f"✓ {result.speakers} спикер(ов) · {format_duration(result.duration_s)} · {result.language}", file=sys.stderr)
    print(f"  {result.transcript_md}", file=sys.stderr)
    print(f"  {result.transcript_json}", file=sys.stderr)
    print(f"  {result.manifest}", file=sys.stderr)
    for subtitle_path in result.subtitle_paths:
        print(f"  {subtitle_path}", file=sys.stderr)
    if result.workdir is not None:
        print(f"  отладочные файлы сохранены: {result.workdir}", file=sys.stderr)


def _stage_progress(stage):
    labels = {"preparing": "Preparing audio…", "asr": "Transcribing…",
              "diar": "Identifying speakers…", "writing": "Writing artifacts…"}
    if sys.stderr.isatty() and stage in labels:
        print(f"\r{labels[stage]}", end="", file=sys.stderr, flush=True)


def main():
    p = argparse.ArgumentParser(prog="transcribe", description=__doc__)
    p.add_argument("inputs", nargs="*", help="локальные медиафайлы или YouTube-URL")
    p.add_argument("--speakers", default="auto",
                   help="auto (детект) | off (без диаризации) | N (число спикеров)")
    p.add_argument("--lang", default="auto", help="ru | en | auto (по умолчанию auto)")
    p.add_argument("--out", default=None, help="конкретная папка вывода")
    p.add_argument("--out-root", default=None,
                   help=f"корневая папка для default output (default {DEFAULT_OUT_ROOT})")
    p.add_argument("--overwrite", action="store_true", help="разрешить перезапись артефактов в --out")
    p.add_argument("--diar-mode", default="streaming", choices=["streaming", "offline"],
                   help="streaming (быстро, ~61x) | offline (точнее DER, медленно)")
    p.add_argument("--asr-model", default="v3", choices=["v3", "v2"])
    p.add_argument("--keep-tmp", action="store_true")
    p.add_argument("--formats", type=_parse_formats, default=(), metavar="LIST",
                   help="additional subtitle artifacts: srt,vtt")
    args = p.parse_args()

    if not args.inputs:
        p.error("укажите хотя бы один источник")
    if len(args.inputs) > 1 and args.out:
        p.error("--out нельзя использовать с несколькими источниками; укажите --out-root")

    failed = False
    for source in args.inputs:
        try:
            r = run(source,
                    out=Path(args.out) if args.out else None,
                    out_root=Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT,
                    speakers=args.speakers, lang=args.lang,
                    diar_mode=args.diar_mode, asr_model=args.asr_model,
                    keep_tmp=args.keep_tmp, formats=args.formats, overwrite=args.overwrite,
                    on_stage=_stage_progress)
        except RunError as exc:
            print(f"transcribe: error: {source}: {exc}", file=sys.stderr)
            failed = True
            continue

        if sys.stderr.isatty():
            print("\r\033[K", end="", file=sys.stderr)
        sys.stdout.write(r.transcript_md.read_text())
        _print_result(r)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
