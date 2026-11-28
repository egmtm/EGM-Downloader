"""v2 on a narrow page: the menu stays inside the window and under the tabs.

When the page is narrow (the Theme Creator docked, or a small window) the v2 tabs move to a row of
their own under the wordmark. The menu (380 px, #hamburger-panel) opens from the end of the tab row.
With the row at the start of the header, the menu hung out of the window on the start side (Chromium,
ten languages, seven widths: up to 78 px in Japanese, 30 px on the right in Arabic), and with two rows of
tabs its fixed top of 44 px covered the lower row. The tab row now stays at the end of the header and
the menu opens 10 px under the last row of tabs: with one row that is the same 44 px as before.
"""
from conftest import read_source
from test_face_v2_fetch_error_wraps import _declarations

CSS = read_source("templates/face_v2_styles.html")


def test_the_tabs_stay_at_the_end_of_the_header_and_the_menu_opens_under_them():
    nav = _declarations(CSS, "body.face-v2 .header-nav")
    assert nav.get("margin-inline-start") == "auto", \
        "a tab row on its own row goes back to the start of the header, and the menu hangs out of the window"
    panel = _declarations(CSS, "body.face-v2 #hamburger-panel")
    assert panel.get("top") == "calc(100% + 10px)", \
        "the menu opens at a fixed height again: with two rows of tabs it covers the lower row"


def test_the_download_all_row_wraps_on_a_narrow_page():
    """The links card cuts what sticks out (overflow hidden). With the Theme Creator docked, the Download All
    buttons were cut by up to 64 px in German, Spanish, French, Japanese and Dutch."""
    row = _declarations(CSS, "body.face-v2 #bulk-actions")
    assert row.get("flex-wrap") == "wrap", "the Download All row no longer wraps, and the links card cuts its last button"


def test_the_subs_tab_reacts_to_the_pointer_like_the_other_tabs():
    """Classic's #subs-btn:hover (templates/index_styles.html) is an id rule, so it outweighed the v2 tab rule:
    in v2 Subs got the accent on all four borders and on its text, the other tabs on the bottom border only."""
    assert "#subs-btn:hover" in read_source("templates/index_styles.html"), "Classic no longer has its own Subs hover: this test is out of date"
    tab = _declarations(CSS, "body.face-v2 .nav-btn:hover")
    subs = _declarations(CSS, "body.face-v2 #subs-btn:hover")
    base = _declarations(CSS, "body.face-v2 .nav-btn")
    assert subs.get("border-bottom-color") == tab.get("border-bottom-color") and subs.get("color") == tab.get("color"), \
        "in v2 the Subs tab reacts to the pointer differently from the other tabs again"
    assert subs.get("border-color") == base.get("border", "").split()[-1], "in v2 the Subs tab's other borders change colour on hover again"
