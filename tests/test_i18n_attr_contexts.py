"""
i18nAttr() (templates/i18n.html) escapes &, " and <. That is all the two places it is used
need: a double quoted attribute value and element content. It does not escape ', so a call
site inside a single quoted attribute would not be safe. The function's comment states that
limit; this test enforces it, because nothing else would notice a new call site breaking it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIRS = [ROOT / "templates", ROOT / "linux" / "templates"]

# An attribute opened with a single quote whose value reaches an i18nAttr(...) call:
#   template literal:      title='${i18nAttr(...)}'   or   title='text ${a + i18nAttr(...)}'
#   string concatenation:  "<b title='" + i18nAttr(...)   or   '<b title=\'' + i18nAttr(...)
SINGLE_QUOTED = [
    re.compile(r"""[\w-]+\s*=\s*'[^'\n]*\$\{[^}\n]*\bi18nAttr\("""),
    re.compile(r"""[\w-]+\s*=\s*\\?'["']?\s*\+\s*i18nAttr\("""),
]


def _single_quoted_use(line):
    return any(p.search(line) for p in SINGLE_QUOTED)


def test_no_i18nattr_call_sits_in_a_single_quoted_attribute():
    calls, offenders = 0, []
    for folder in TEMPLATE_DIRS:
        for path in sorted(folder.rglob("*.html")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                calls += line.count("i18nAttr(")
                if _single_quoted_use(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert calls, "no i18nAttr call found; this guard would pass for nothing"
    assert not offenders, "i18nAttr does not escape ' (use a double quoted attribute or esc()):\n" + "\n".join(offenders)


def test_the_detector_flags_single_quoted_use_and_accepts_the_normal_ones():
    flagged = [
        "<b title='${i18nAttr('k', 'x')}'>",
        "<b onclick='f(${i18nAttr('k', 'x')})'>",
        "<b data-x='a ${n + i18nAttr('k', 'x')} b'>",
        "html = \"<b title='\" + i18nAttr('k', 'x') + \"'>\";",
        "html = '<b title=\\'' + i18nAttr('k', 'x') + '\\'>';",
    ]
    fine = [
        '<b title="${i18nAttr(\'k\', \'x\')}">',
        "<span>${i18nAttr('k', 'x')}</span>",
        "<option value='a'>${i18nAttr('k', 'x')}</option>",
        "html = '<b title=\"' + i18nAttr('k', 'x') + '\">';",
        "const s = cond ? 'a' : i18nAttr('k', 'x');",
    ]
    assert [s for s in flagged if not _single_quoted_use(s)] == []
    assert [s for s in fine if _single_quoted_use(s)] == []
