"""The main window loads the v2 stylesheet, and no other window takes part in the Face.

v2 is the default Face: the boot script puts body.face-v2 on at every start. If index.html stopped
including the stylesheet, the class would be on with no rule behind it and every install would
show Classic while the dropdown says v2; no test failed when the include was removed. It has to
come after index_styles.html (and the theme blocks that file brings in): two rules of the same
weight are decided by their order. The other windows (History, Subscriptions, Themes, Console)
keep their look whatever the Face is, so they include neither the stylesheet nor the Face script
(that the script runs first in the main window is covered by the frontend tests).
"""
import re

from conftest import read_source

OTHER_WINDOWS = ("history.html", "subscriptions.html", "themes.html", "console.html")


def test_the_main_page_loads_the_v2_stylesheet_right_after_the_main_styles():
    page = read_source("templates/index.html")
    head = page[:page.index("</head>")]
    assert re.search(r"<style>\s*\{% include 'index_styles.html' %\}\s*</style>\s*"
                     r"<style>\s*\{% include 'face_v2_styles.html' %\}\s*</style>", head), \
        "index.html no longer includes face_v2_styles.html in a style element right after index_styles.html"
    assert page.count("face_v2_styles.html") == 1


def test_no_other_window_loads_the_v2_stylesheet_or_the_face_script():
    for name in OTHER_WINDOWS:
        source = read_source(f"templates/{name}")
        assert "face_v2_styles" not in source and "_face.html" not in source and "face-v2" not in source, \
            f"templates/{name} takes part in the Face: only the main window does"
