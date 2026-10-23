"""scripts/verify-theme-batch.py: new-theme mode and --polish mode, run on documents built from the real catalog."""
import importlib.util
import os
import re
import subprocess
import sys

from conftest import ROOT

SCRIPT = os.path.join(ROOT, "scripts", "verify-theme-batch.py")
_spec = importlib.util.spec_from_file_location("verify_theme_batch", SCRIPT)
vtb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vtb)

STYLES = open(os.path.join(ROOT, "templates", "theme_styles.html"), encoding="utf-8").read()
BLOCKS = dict(vtb._BLOCK.findall(STYLES))
CATALOG = vtb.get_catalog()
CLEAN = "pitch"  # a plain hex theme that declares the full variable set and whose swatch data equals its CSS


def value(key, var):
    return re.search(vtb._START + rf"{var}:\s*([^;\n]*);", BLOCKS[key], re.M).group(1).strip()


def block(key, rename=None, setvar=None):
    """The real CSS block for key, optionally under another name and with one variable set to a new value."""
    body = BLOCKS[key]
    if setvar:
        body, n = re.subn(rf"({vtb._START}{setvar[0]}:\s*)[^;\n]*;", lambda m: f"{m.group(1)}{setvar[1]};", body, flags=re.M)
        assert n == 1, f"{setvar[0]} not found once in the {key} block"
    return f"body.{rename or key} {{{body}\n}}"


def entry(key, label=None, bg=None, surf=None, acc=None, cat=None):
    lab, b, s, a, c = CATALOG[key]
    return f"{key}: {{label:'{label or lab}', bg:'{bg or b}', surf:'{surf or s}', acc:'{acc or a}', cat:'{cat or c}'}},"


def doc(blocks, entries=None):
    out = "# Batch\n\n### Section 1 -- CSS blocks\n**Target:** `templates/theme_styles.html`\n```css\n" + "\n\n".join(blocks) + "\n```\n"
    if entries is not None:
        out += "\n### Section 2 -- THEME_DATA entries\n```js\n" + "\n".join(entries) + "\n```\n"
    return out


def run(tmp_path, text, polish):
    path = tmp_path / "batch.md"
    path.write_text(text, encoding="utf-8")
    cmd = [sys.executable, SCRIPT] + (["--polish"] if polish else []) + [str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def test_the_parsers_cover_the_whole_catalog():
    entries = open(os.path.join(ROOT, "templates", "theme_data.html"), encoding="utf-8").read().count("cat:'")
    assert len(CATALOG) == entries, "a THEME_DATA entry was not parsed (label quoting? key quoting?)"
    assert len(BLOCKS) == entries - 1, "a CSS block was not parsed (every theme but custom has one)"


def test_no_built_in_block_trips_the_typo_check_except_the_known_bugs():
    flagged = {k for k, b in BLOCKS.items() if list(vtb.malformed_values(b))}
    assert flagged <= {"amiga", "bigblue"}, f"the typo check has a false positive: {sorted(flagged)}"


def test_new_mode_flags_an_existing_key_as_a_collision(tmp_path):
    code, out = run(tmp_path, doc([block(CLEAN)], [entry(CLEAN)]), polish=False)
    assert code == 1 and "COLLISION" in out


def test_polish_accepts_unchanged_blocks_without_theme_data(tmp_path):
    keys = [CLEAN, "midnight", "ocean", "aurora-deep"]  # the last three are gradient themes, aurora-deep has a hyphen
    code, out = run(tmp_path, doc([block(k) for k in keys]), polish=True)
    assert code == 0, out
    assert "All 4 themes check out clean" in out


def test_polish_accepts_unchanged_blocks_with_their_theme_data(tmp_path):
    keys = [CLEAN, "midnight", "ocean", "aurora-deep"]
    code, out = run(tmp_path, doc([block(k) for k in keys], [entry(k) for k in keys]), polish=True)
    assert code == 0, out


def test_polish_flags_a_new_key(tmp_path):
    code, out = run(tmp_path, doc([block(CLEAN, rename="brandnewtheme")]), polish=True)
    assert code == 1 and "brandnewtheme: NEW KEY" in out


def test_polish_flags_a_color_change_until_the_theme_data_entry_comes_with_it(tmp_path):
    changed = block(CLEAN, setvar=("--acc", "#123456"))
    code, out = run(tmp_path, doc([changed]), polish=True)
    assert code == 1 and "send a THEME_DATA entry" in out
    code, out = run(tmp_path, doc([changed], [entry(CLEAN, acc="#123456")]), polish=True)
    assert code == 0, out
    code, out = run(tmp_path, doc([changed], [entry(CLEAN)]), polish=True)
    assert code == 1 and "THEME_DATA says" in out


def test_polish_keeps_the_label_and_the_category(tmp_path):
    code, out = run(tmp_path, doc([block(CLEAN)], [entry(CLEAN, label="Another Name", cat="nowhere")]), polish=True)
    assert code == 1 and "label changed" in out and "category changed" in out


def test_polish_catches_a_stray_quote_and_a_seven_digit_hex(tmp_path):
    quote = block(CLEAN, setvar=("--surf2", value(CLEAN, "--surf2") + "'"))
    code, out = run(tmp_path, doc([quote]), polish=True)
    assert code == 1 and "stray quote" in out
    digits = block(CLEAN, setvar=("--muted", "#0040808"))
    code, out = run(tmp_path, doc([digits]), polish=True)
    assert code == 1 and "not a color" in out
    typo = block(CLEAN, setvar=("--green", "--40a870"))
    code, out = run(tmp_path, doc([typo]), polish=True)
    assert code == 1 and "looks like a typo" in out


def test_polish_keeps_a_gradient_theme_a_gradient(tmp_path):
    bg = value("ocean", "--bg")
    flat = block("ocean", setvar=("--bg", "#e0f2fe"))
    code, out = run(tmp_path, doc([flat]), polish=True)
    assert code == 1 and "keep their gradient" in out
    other = block("ocean", setvar=("--bg", bg.replace("#e0f2fe", "#ffffff", 1)))
    code, out = run(tmp_path, doc([other]), polish=True)
    assert code == 1 and "first color stop" in out


def test_new_mode_still_requires_a_hex_bg(tmp_path):
    new = block("ocean", rename="brandnewocean")
    code, out = run(tmp_path, doc([new], [entry("ocean").replace("ocean:", "brandnewocean:")]), polish=False)
    assert code == 1 and "not a valid hex color" in out


def test_the_older_delivery_headings_still_parse(tmp_path):
    old = ("## CSS -- paste into theme_styles.html\n\n```css\n" + block(CLEAN, rename="brandnewtheme") + "\n```\n\n"
           "## THEME_DATA entries\n\n```js\n" + entry(CLEAN).replace(f"{CLEAN}:", "brandnewtheme:") + "\n```\n")
    code, out = run(tmp_path, old, polish=False)
    assert code == 0, out


def test_help_and_bad_arguments_print_a_message_not_a_traceback(tmp_path):
    for args, code, text in ((["--polish", "--help"], 0, "--polish checks replacements"),
                             (["--nope"], 1, "Usage:"),
                             ([], 1, "Usage:"),
                             ([str(tmp_path / "missing.md")], 1, "File not found")):
        r = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == code and text in r.stdout and "Traceback" not in r.stderr, (args, r.stdout, r.stderr)
