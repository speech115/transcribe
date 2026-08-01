#!/usr/bin/env python3
"""Тесты merge-логики: назначение спикеров словам + группировка в реплики."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge import assign_speaker, clean_fillers, merge_words_to_turns


def w(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_assign_by_max_overlap():
    diar = [(0.0, 5.0, "S1"), (5.0, 10.0, "S2")]
    assert assign_speaker(0.5, 1.0, diar) == "S1"
    assert assign_speaker(6.0, 7.0, diar) == "S2"
    # слово на границе: больше перекрытия со вторым (S1=0.3, S2=0.5)
    assert assign_speaker(4.7, 5.5, diar) == "S2"


def test_assign_nearest_speaker_in_short_vad_gap():
    diar = [(3.5, 9.9, "S1"), (11.4, 13.5, "S1")]
    # ASR иногда ставит слово в микрозазор между diarization-сегментами.
    assert assign_speaker(11.12, 11.28, diar) == "S1"
    # Но через длинную паузу к случайному спикеру не приклеиваем.
    assert assign_speaker(20.0, 20.2, diar) is None


def test_overlapping_segments_prefer_higher_quality_speaker():
    diar = [(252.3, 259.9, "S1", 0.31), (252.4, 255.8, "S2", 0.39)]
    assert assign_speaker(253.1, 253.4, diar) == "S2"


def test_no_diarization_groups_by_gap():
    words = [w(0.0, 0.5, "привет"), w(0.6, 1.0, "мир"), w(5.0, 5.4, "снова")]
    turns = merge_words_to_turns(words, [], max_gap=1.5)
    # пауза 4с между "мир" и "снова" => две реплики
    assert len(turns) == 2
    assert turns[0]["text"] == "привет мир"
    assert turns[1]["text"] == "снова"
    assert all(t["speaker"] is None for t in turns)


def test_two_speakers_alternating():
    diar = [(0.0, 2.0, "S1"), (2.0, 4.0, "S2"), (4.0, 6.0, "S1")]
    words = [w(0.1, 0.5, "да"), w(0.6, 1.8, "согласен"),
             w(2.1, 2.5, "нет"), w(2.6, 3.8, "погоди"),
             w(4.1, 4.5, "ладно")]
    turns = merge_words_to_turns(words, diar)
    assert [t["speaker"] for t in turns] == ["S1", "S2", "S1"]
    assert turns[0]["text"] == "да согласен"
    assert turns[1]["text"] == "нет погоди"
    assert turns[2]["text"] == "ладно"
    assert turns[0]["start"] == 0.1


def test_same_speaker_long_paragraph_splits_on_gap():
    diar = [(0.0, 100.0, "S1")]
    words = [w(0.0, 0.4, "а"), w(0.5, 0.9, "б"), w(20.0, 20.4, "в")]
    turns = merge_words_to_turns(words, diar, max_gap=2.0)
    # один спикер, но большая пауза => два абзаца
    assert len(turns) == 2
    assert turns[0]["speaker"] == "S1" and turns[1]["speaker"] == "S1"


def test_clean_fillers_removes_hesitations_but_keeps_meaningful_like():
    assert clean_fillers("Um, I like this, er, really.", "en") == "I like this, really."
    assert clean_fillers("Э-э, мм, это ну важно.", "ru") == "это важно."
    assert clean_fillers("Um, э-э, hello.", "mixed") == "hello."


def test_merge_clean_fillers_applies_to_turn_text_only():
    words = [w(0.0, 0.2, "Um,"), w(0.3, 0.6, "hello"), w(0.7, 0.9, "uh")]
    turns = merge_words_to_turns(words, [], clean_fillers=True, lang="en")

    assert turns[0]["text"] == "hello"
    assert [word["text"] for word in words] == ["Um,", "hello", "uh"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
