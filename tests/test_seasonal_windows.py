"""
Seasonal themes: one window table, shared by the main window picker and the
Themes window, so the two cannot drift apart again.

The windows live in templates/theme_data.html (SEASONAL_FIXED / SEASONAL_VARIABLE
plus seasonalVisibleKeys). js/_theme.html (main picker) and themes.html (Themes
window) both call it. Root = Linux byte parity is covered by
test_parity.test_theme_counts_linux_parity.
"""
import re
from conftest import read_source


def _theme_data():
    return read_source("templates/theme_data.html")


def _seasonal_keys():
    return set(re.findall(r"^\s*'?([\w-]+)'?\s*:\s*\{label:[^\n]*cat:'seasonal'", _theme_data(), re.MULTILINE))


def _window_keys():
    data = _theme_data()
    fixed = re.search(r"const SEASONAL_FIXED\s*=\s*\{(.*?)\n\};", data, re.DOTALL)
    variable = re.search(r"const SEASONAL_VARIABLE\s*=\s*\{(.*?)\n\};", data, re.DOTALL)
    assert fixed and variable, "SEASONAL_FIXED / SEASONAL_VARIABLE not found in theme_data.html"
    return (set(re.findall(r"^\s*(\w+):", fixed.group(1), re.MULTILINE)),
            set(re.findall(r"^\s*(\w+):", variable.group(1), re.MULTILINE)))


def test_every_seasonal_theme_has_exactly_one_window():
    seasonal = _seasonal_keys()
    fixed, variable = _window_keys()
    assert seasonal, "no seasonal themes found"
    assert not (fixed & variable), f"in both window tables: {sorted(fixed & variable)}"
    assert seasonal - (fixed | variable) == set(), f"seasonal themes with no window: {sorted(seasonal - (fixed | variable))}"
    assert (fixed | variable) - seasonal == set(), f"windows for non-seasonal themes: {sorted((fixed | variable) - seasonal)}"


def test_every_seasonal_row_in_the_main_picker_is_gated():
    """A seasonal row without data-seasonal and display:none shows all year."""
    index = read_source("templates/index.html")
    rows = re.findall(r'<div class="theme-row" data-theme="([\w-]+)"([^>]*)>', index)
    seasonal = _seasonal_keys()
    gated = {k for k, attrs in rows if 'data-seasonal="true"' in attrs}
    assert seasonal - gated == set(), f"seasonal rows missing data-seasonal: {sorted(seasonal - gated)}"
    assert gated - seasonal == set(), f"data-seasonal on non-seasonal rows: {sorted(gated - seasonal)}"
    for k, attrs in rows:
        if k in seasonal:
            assert 'style="display:none"' in attrs, f"seasonal row {k} is not hidden by default"


def test_both_windows_use_the_shared_table():
    """Neither consumer may carry a private window table again."""
    for rel in ("templates/js/_theme.html", "templates/themes.html"):
        src = read_source(rel)
        assert "seasonalVisibleKeys(" in src, f"{rel} does not call the shared seasonalVisibleKeys()"
        for private in ("variableDates", "varDates", "const windows"):
            assert private not in src, f"{rel} has its own seasonal table again ({private})"
    assert "{% include 'theme_data.html' %}" in read_source("templates/js/_theme.html")
    assert "{% include 'theme_data.html' %}" in read_source("templates/themes.html")
