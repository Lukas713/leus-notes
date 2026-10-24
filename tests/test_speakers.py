from leus_notes.diarizer import Turn
from leus_notes.speakers import (
    ME,
    THEM,
    TurnIndex,
    Utterance,
    carry_names,
    load_utterances,
    renumber,
    save_utterances,
    single_speaker,
    speaker_ids,
    split_by_turns,
)
from leus_notes.transcriber import Segment, Word


def test_speaker_at_picks_largest_overlap():
    index = TurnIndex([Turn(0, 5, "A"), Turn(4, 10, "B")])
    assert index.speaker_at(3.0, 4.5) == "A"
    assert index.speaker_at(4.2, 6.0) == "B"


def test_speaker_at_falls_back_to_nearest_turn():
    index = TurnIndex([Turn(0, 2, "A"), Turn(10, 12, "B")])
    assert index.speaker_at(3.0, 3.5) == "A"
    assert index.speaker_at(8.5, 9.0) == "B"


def test_speaker_at_sees_long_turns_that_started_much_earlier():
    index = TurnIndex([Turn(0, 100, "A"), Turn(50, 51, "B")])
    assert index.speaker_at(90, 91) == "A"


def test_split_by_turns_breaks_a_segment_at_speaker_changes():
    words = (
        Word(0.0, 0.5, " Friday"),
        Word(0.5, 1.0, " is"),
        Word(1.0, 1.5, " tight."),
        Word(2.0, 2.5, " Monday"),
        Word(2.5, 3.0, " works."),
    )
    segments = [Segment(0.0, 3.0, "Friday is tight. Monday works.", words)]
    turns = [Turn(0.0, 1.8, "SPEAKER_01"), Turn(1.8, 3.0, "SPEAKER_00")]
    assert split_by_turns(segments, turns) == [
        Utterance(0.0, 1.5, "SPEAKER_01", "Friday is tight."),
        Utterance(2.0, 3.0, "SPEAKER_00", "Monday works."),
    ]


def test_split_by_turns_without_words_uses_whole_segment():
    segments = [Segment(5.0, 7.0, "Hello there.")]
    assert split_by_turns(segments, [Turn(4.0, 8.0, "X")]) == [Utterance(5.0, 7.0, "X", "Hello there.")]


def test_renumber_by_first_appearance_keeps_me_and_them():
    utterances = [
        Utterance(10, 11, "SPEAKER_00", "b"),
        Utterance(0, 1, ME, "a"),
        Utterance(2, 3, "SPEAKER_03", "c"),
        Utterance(12, 13, THEM, "d"),
        Utterance(14, 15, "SPEAKER_03", "e"),
    ]
    assert [utterance.speaker for utterance in renumber(utterances)] == [ME, "1", "2", THEM, "1"]


def test_speaker_ids_in_order_of_first_appearance():
    utterances = [Utterance(5, 6, "2", "x"), Utterance(1, 2, "1", "y"), Utterance(0, 1, ME, "z")]
    assert speaker_ids(utterances) == ["1", "2"]


def test_carry_names_follows_majority_overlap():
    old = [Utterance(0, 10, "1", "a"), Utterance(10, 20, "2", "b"), Utterance(20, 30, "3", "c")]
    new = [Utterance(0, 10, "2", "a"), Utterance(10, 20, "1", "b"), Utterance(20, 22, "3", "c"), Utterance(22, 30, "4", "c")]
    assert carry_names(old, new, {"1": "Marko", "2": "Ana", "3": "Ivan"}) == {
        "2": "Marko",
        "1": "Ana",
        "3": "Ivan",
        "4": "Ivan",
    }


def test_carry_names_keeps_a_name_given_to_two_merged_speakers():
    old = [Utterance(0, 9, "1", "a"), Utterance(9, 18, "2", "b"), Utterance(18, 20, "3", "c")]
    new = [Utterance(0, 20, "1", "abc")]
    assert carry_names(old, new, {"1": "Marko", "2": "Marko", "3": "Ana"}) == {"1": "Marko"}


def test_carry_names_skips_unclear_matches():
    old = [Utterance(0, 10, "1", "a")]
    new = [Utterance(0, 4, "1", "a"), Utterance(20, 30, "1", "b")]
    assert carry_names(old, new, {"1": "Marko"}) == {}


def test_single_speaker_and_storage_round_trip(tmp_path):
    utterances = single_speaker([Segment(0, 1, "Bok"), Segment(2, 3, "Kako si?")], ME)
    save_utterances(tmp_path / "segments.json", utterances)
    assert load_utterances(tmp_path / "segments.json") == utterances
