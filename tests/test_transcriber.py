from leus_notes.transcriber import ChannelTranscript, Segment, Word, group_clips, merge_regions, split_on_pauses


def test_group_clips_collects_about_thirty_seconds_of_speech_per_group():
    clips = [(0.0, 20.0), (25.0, 40.0), (100.0, 105.0), (200.0, 230.0), (300.0, 302.0)]
    assert group_clips(clips) == [[(0.0, 20.0), (25.0, 40.0)], [(100.0, 105.0), (200.0, 230.0)], [(300.0, 302.0)]]
    assert group_clips([]) == []


def test_merge_regions_joins_short_gaps_only():
    regions = [(0.5, 2.0), (2.6, 4.0), (9.0, 11.0), (11.9, 12.5), (20.0, 21.0)]
    assert merge_regions(regions) == [(0.5, 4.0), (9.0, 12.5), (20.0, 21.0)]
    assert merge_regions([]) == []


def test_split_on_pauses_separates_turns_glued_by_the_silence_filter():
    words = (
        Word(0.8, 1.2, " Dobar"),
        Word(1.2, 1.6, " dan."),
        Word(14.0, 14.5, " Trebam"),
        Word(14.5, 15.0, " pet"),
        Word(15.6, 16.0, " uzoraka."),
    )
    segment = Segment(0.8, 16.0, "Dobar dan. Trebam pet uzoraka.", words)
    assert split_on_pauses(segment) == [
        Segment(0.8, 1.6, "Dobar dan.", words[:2]),
        Segment(14.0, 16.0, "Trebam pet uzoraka.", words[2:]),
    ]


def test_split_on_pauses_without_words_keeps_the_segment():
    segment = Segment(0.0, 2.0, "Hello.")
    assert split_on_pauses(segment) == [segment]


def test_channel_transcript_round_trip():
    transcript = ChannelTranscript(("hr", "en"), 49.0, (Segment(1.0, 2.0, "Bok.", (Word(1.0, 2.0, " Bok."),)),))
    assert ChannelTranscript.from_dict(transcript.to_dict()) == transcript
