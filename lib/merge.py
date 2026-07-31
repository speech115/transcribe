"""Merge ASR word-timings со speaker-сегментами диаризации в реплики (turns).

Чистые функции, без внешних зависимостей. Покрыто tests/test_merge.py.
"""
from typing import List, Optional, Tuple, Dict, Union

# diar-сегмент = (start, end, speaker) или (start, end, speaker, quality)
DiarSeg = Union[Tuple[float, float, str], Tuple[float, float, str, float]]
# слово = {"start": float, "end": float, "text": str}
Word = Dict


def assign_speaker(
    w_start: float,
    w_end: float,
    diar: List[DiarSeg],
    max_nearest_gap: float = 5.0,
) -> Optional[str]:
    """Спикер с максимальным перекрытием со словом.

    ASR и diarization часто дают немного разные границы речи. Если прямого
    перекрытия нет, берём ближайший diar-сегмент в пределах max_nearest_gap.
    """
    word_dur = max(w_end - w_start, 0.001)
    overlaps = []
    best: Optional[str] = None
    best_ov = 0.0
    for seg in diar:
        s, e, spk = seg[:3]
        quality = float(seg[3]) if len(seg) > 3 else 1.0
        ov = min(w_end, e) - max(w_start, s)
        if ov > best_ov:
            best_ov, best = ov, spk
        if ov > 0:
            overlaps.append((ov / word_dur, quality, ov, spk))
    if overlaps:
        significant = [item for item in overlaps if item[0] >= 0.35]
        if significant:
            return max(significant, key=lambda item: (item[1], item[0], item[2]))[3]
    if best is not None:
        return best

    nearest: Optional[str] = None
    nearest_gap = max_nearest_gap
    for seg in diar:
        s, e, spk = seg[:3]
        if w_end < s:
            gap = s - w_end
        elif w_start > e:
            gap = w_start - e
        else:
            gap = 0.0
        if gap <= nearest_gap:
            nearest_gap, nearest = gap, spk
    return nearest


def merge_words_to_turns(
    words: List[Word],
    diar: List[DiarSeg],
    max_gap: float = 1.5,
    max_chars: int = 600,
) -> List[Dict]:
    """Группирует подряд идущие слова одного спикера в реплики.

    Новая реплика начинается при смене спикера, паузе > max_gap,
    либо когда текущая реплика превышает max_chars (чтобы абзацы не разрастались).
    """
    turns: List[Dict] = []
    for w in words:
        spk = assign_speaker(w["start"], w["end"], diar) if diar else None
        last = turns[-1] if turns else None
        same = (
            last is not None
            and last["speaker"] == spk
            and (w["start"] - last["end"]) <= max_gap
            and len(last["text"]) < max_chars
        )
        if same:
            sep = "" if last["text"].endswith(" ") else " "
            last["text"] += sep + w["text"].strip()
            last["end"] = w["end"]
        else:
            turns.append(
                {"speaker": spk, "start": w["start"], "end": w["end"], "text": w["text"].strip()}
            )
    return turns
