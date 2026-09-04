from lib.merge import assign_speaker, merge_words_to_turns


def test_assign_speaker_prefers_overlap():
    assert assign_speaker(1, 2, [(0, 1.5, "S1"), (1.5, 3, "S2")]) == "S1"


def test_merge_groups_words_and_splits_speakers():
    words = [{"start": 0, "end": 1, "text": "hello"}, {"start": 1.1, "end": 2, "text": "world"}]
    assert merge_words_to_turns(words, [(0, 1, "S1"), (1.5, 3, "S2")])[0]["text"] == "hello"
