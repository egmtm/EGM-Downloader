"""What the GitHub workflows run, pinned to the decisions behind them.

* The app ships Python 3.11 (python-build-standalone 3.11.18 in every edition), and CI ran its tests
  on 3.12 only: syntax or library behaviour that 3.12 accepts and 3.11 refuses would pass CI and
  break the shipped app. The Tests job runs on 3.11 and 3.12, the lint and the validator on 3.11.

Plain text checks: the CI image has no YAML library installed for the tests."""
import re

from conftest import read_source


def _step(text, name):
    """The text of one workflow step, from its name to the next step."""
    i = text.index(f"- name: {name}")
    j = text.find("\n      - name:", i + 1)
    return text[i:j if j != -1 else len(text)]


def test_the_tests_job_runs_on_the_shipped_python_and_the_next_one():
    text = read_source(".github/workflows/tests.yml")
    assert re.search(r'python-version:\s*\[\s*"3\.11",\s*"3\.12"\s*\]', text), "a matrix of 3.11 and 3.12"
    assert 'python-version: ${{ matrix.python-version }}' in _step(text, "Set up Python")


def test_the_lint_and_the_validator_run_on_the_shipped_python():
    for rel in (".github/workflows/lint-python.yml", ".github/workflows/validate-version.yml"):
        text = read_source(rel)
        assert re.search(r"python-version:\s*'3\.11'", text), rel
        assert "3.12" not in text, rel
