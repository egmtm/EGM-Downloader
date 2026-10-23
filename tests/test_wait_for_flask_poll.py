"""The shells poll the backend every 250 ms for up to 3 minutes before the window loads.

The poll used to be one probe per second, so a backend that was ready after 0.2 s waited for the next
tick. The budget is a time and not a count of attempts: a refused connection takes about 2 s to fail on
Windows, so counting attempts would not add up to the 3 minutes the error text promises there. The three
main.js files must carry the same values, and nothing else in the test suite pins them.
"""
import re

from conftest import read_source

PLATFORMS = ("windows", "mac", "linux")
SIGNATURE = re.compile(r"function waitForFlask\(budgetMs = (\d+), delay = (\d+)\) \{")


def _function(platform):
    src = read_source(f"{platform}/electron/main.js")
    start = src.index("function waitForFlask(")
    return src[start:src.index("\n}\n", start)]


def test_all_three_shells_poll_every_250_ms_within_three_minutes():
    for platform in PLATFORMS:
        m = SIGNATURE.search(_function(platform))
        assert m, platform
        assert (int(m.group(1)), int(m.group(2))) == (180000, 250), platform


def test_the_budget_is_a_deadline_not_an_attempt_count():
    for platform in PLATFORMS:
        body = _function(platform)
        assert "retries" not in body, platform
        assert body.count("Date.now() + budgetMs") == 1, platform
        assert body.count("if (Date.now() >= deadline) {") == 1, platform
        assert body.count("setTimeout(try_, delay);") == 1, platform
        # one request at a time, each cut off after 900 ms (unchanged)
        assert body.count("req.setTimeout(900, () => { req.destroy(); });") == 1, platform
        assert "The backend did not start within 3 minutes." in body, platform


def test_the_loop_is_the_same_in_the_three_shells_apart_from_the_error_text():
    def norm(platform):
        return re.sub(r"reject\(new Error\('[^']*'\)\);", "reject(ERR);", _function(platform))
    assert norm("windows") == norm("mac") == norm("linux")
