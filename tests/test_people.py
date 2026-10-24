import pytest

from leus_notes.people import PeopleCount, PeopleCountError


@pytest.mark.parametrize("text", [None, "", "auto", "AUTO", "  "])
def test_auto_when_not_given(text):
    people = PeopleCount.parse(text)
    assert people.is_auto
    assert str(people) == "auto"
    assert people.diarization_options() == {}
    assert people.needs_speaker_separation()


def test_exact_count_excludes_me_from_voices_to_find():
    people = PeopleCount.parse("4")
    assert str(people) == "4"
    assert people.diarization_options() == {"num_speakers": 3}


def test_two_people_need_no_speaker_separation():
    assert not PeopleCount.parse(2).needs_speaker_separation()


def test_range():
    people = PeopleCount.parse(" 3 - 5 ")
    assert str(people) == "3-5"
    assert people.diarization_options() == {"min_speakers": 2, "max_speakers": 4}
    assert people.needs_speaker_separation()


@pytest.mark.parametrize("text", ["1", "0", "5-3", "three", "3-", "-3", "2.5"])
def test_invalid(text):
    with pytest.raises(PeopleCountError):
        PeopleCount.parse(text)
