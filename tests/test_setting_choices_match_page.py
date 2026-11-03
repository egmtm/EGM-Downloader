"""The settings route keeps a choice setting only when its value is one the page offers.

_SETTING_CHOICES (in all three backends) lists the allowed values of five settings, and the
settings route drops anything else. Nothing linked that list to the page, so a new option added
to one of these selects without the list would look fine on screen and silently not be saved.
This reads the option values from the page and compares them with the list in each backend.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKENDS = ("app.py", "mac/app.py", "linux/app.py")

# setting key -> (page file, id of the select that offers it)
SELECTS = {
    "output_format":        ("templates/index.html", "output-format-sel"),
    "default_audio_format": ("templates/index.html", "default-audio-fmt-sel"),
    "yt_dlp_channel":       ("templates/index.html", "adv-ytdlp-channel"),
    "ffmpeg_channel":       ("templates/index.html", "adv-ffmpeg-channel"),
    "random_theme_scope":   ("templates/themes.html", "random-scope"),
}


def _page_values(page, select_id):
    """The value= of every <option> of the select with this id."""
    src = (ROOT / page).read_text(encoding="utf-8")
    start = src.index(f'<select id="{select_id}"')
    body = src[start:src.index("</select>", start)]
    return re.findall(r'<option value="([^"]+)"', body)


def _backend_choices(backend):
    tree = ast.parse((ROOT / backend).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_SETTING_CHOICES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{backend} has no _SETTING_CHOICES")


def test_the_page_offers_something_for_every_choice_setting():
    for key, (page, select_id) in SELECTS.items():
        values = _page_values(page, select_id)
        assert values, f"{select_id} in {page} has no options"
        assert len(values) == len(set(values)), f"{select_id} offers a value twice"


@pytest.mark.parametrize("backend", BACKENDS)
def test_every_choice_setting_is_tied_to_a_select(backend):
    assert set(_backend_choices(backend)) == set(SELECTS), (
        "_SETTING_CHOICES and SELECTS in this test must name the same settings; add the select "
        "of a new choice setting to SELECTS")


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("key", sorted(SELECTS))
def test_the_allowed_values_equal_the_options_of_the_page(backend, key):
    page, select_id = SELECTS[key]
    page_values = _page_values(page, select_id)
    allowed = _backend_choices(backend)[key]
    assert sorted(page_values) == sorted(allowed), (
        f"{select_id} offers {page_values} but {backend} saves only {list(allowed)} for {key}")
