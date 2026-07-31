#!/usr/bin/env python3
"""Собрать корпус прогонов: manifest.json -> corpus.jsonl + сводка.

Корпус — база для исследований (ETA-калибровка, бенчмарки движка).
Одна строка JSONL = один завершённый прогон транскрибации.
"""
import argparse
import json
import sys
from pathlib import Path

FIELDS = ["source", "duration", "speakers", "language", "engine", "generated",
          "out_dir", "asr_rtf", "asr_model", "diar_mode", "speakers_arg",
          "words", "turns", "engine_binary"]
TIMING_FIELDS = ["prep_s", "asr_s", "diar_s"]


def collect(root: Path) -> list[dict]:
    rows = []
    for mf in sorted(root.rglob("manifest.json")):
        try:
            m = json.loads(mf.read_text())
        except Exception:
            continue
        row = {k: m.get(k) for k in FIELDS}
        t = m.get("timings_s") or {}
        row.update({k: t.get(k) for k in TIMING_FIELDS})
        dur, asr_s = row.get("duration"), row.get("asr_s")
        if dur and asr_s:
            row["measured_rtf"] = round(dur / asr_s, 2)
        row["manifest_path"] = str(mf)
        rows.append(row)
    rows.sort(key=lambda r: r.get("generated") or "")
    return rows


def summarize(rows: list[dict]) -> str:
    if not rows:
        return "прогонов не найдено"
    n = len(rows)
    durs = [r["duration"] for r in rows if r.get("duration")]
    rtf = [r["measured_rtf"] for r in rows if r.get("measured_rtf")]
    words = [r["words"] for r in rows if r.get("words") is not None]
    lines = [
        f"прогонов: {n}",
        f"суммарное аудио: {sum(durs) / 60:.1f} мин" if durs else "",
        f"средний RTF: {sum(rtf) / len(rtf):.1f}x" if rtf else "",
        f"всего слов: {sum(words)}" if words else "",
    ]
    langs = {}
    for r in rows:
        langs[r.get("language")] = langs.get(r.get("language"), 0) + 1
    if langs:
        lines.append("языки: " + ", ".join(f"{k}: {v}" for k, v in sorted(langs.items())))
    return "\n".join(l for l in lines if l)


def main():
    p = argparse.ArgumentParser(prog="collect_corpus",
                                description="manifest.json -> corpus.jsonl")
    p.add_argument("--root", default=str(Path.home() / "Downloads" / "transcripts"),
                   help="корень поиска прогонов (default: ~/Downloads/transcripts)")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                        / "docs" / "research" / "corpus.jsonl"))
    args = p.parse_args()

    rows = collect(Path(args.root))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(summarize(rows))
    print(f"-> {out} ({len(rows)} записей)")


if __name__ == "__main__":
    main()
