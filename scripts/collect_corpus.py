#!/usr/bin/env python3
"""Собрать корпус прогонов: manifest.json -> corpus.jsonl + сводка.

Корпус — база для исследований (ETA-калибровка, бенчмарки движка).
Одна строка JSONL = один завершённый прогон транскрибации.
The run module owns the manifest schema and corpus-row projection
(Manifest.from_dict / to_corpus_row); this script does not redeclare them.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
from run import Manifest


def collect(root: Path) -> list[dict]:
    rows = []
    for mf in sorted(root.rglob("manifest.json")):
        try:
            m = json.loads(mf.read_text())
        except Exception:
            continue
        rows.append(Manifest.from_dict(m).to_corpus_row(mf))
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
        language = r.get("language") or "unknown"
        langs[language] = langs.get(language, 0) + 1
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
