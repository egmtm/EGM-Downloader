"""The channel panel's top row in Subscriptions: the sort select, Delete, then Fetch at the far end.

Fetch is the common action, so it sits where the hand goes first; Delete sits next to it and still asks before
it removes anything. "Mark all seen" below is sized from both buttons, found by their onclick, not their place.
"""
import re

from conftest import read_source

PAGE = read_source("templates/subscriptions.html")


def _row():
    m = re.search(r'<select id="sort-select".*?</select>(.*?)\n\s*</div>', PAGE, re.S)
    assert m, "the channel panel's top row was not found"
    return re.findall(r"<button\b[^>]*onclick=\"([a-zA-Z]+)\(", m.group(1))


def test_fetch_is_at_the_far_end_and_delete_just_before_it():
    assert _row() == ["removeSub", "fetchVideos"], "the channel panel's buttons are in another order again"


def test_delete_still_asks_before_it_removes_the_channel():
    body = re.search(r"async function removeSub\(id\) \{(.*?)\n\}", PAGE, re.S).group(1)
    assert "if (!await egmConfirm(" in body.split("subs = subs.filter", 1)[0]


def test_mark_all_seen_finds_both_buttons_by_what_they_do():
    assert "document.querySelector('.fetch-btn[onclick*=\"fetchVideos\"]')" in PAGE
    assert "document.querySelector('.fetch-btn[onclick*=\"removeSub\"]')" in PAGE
