"""What the GitHub workflows run, pinned to the decisions behind them.

* The app ships Python 3.11 (python-build-standalone 3.11.18 in every edition), and CI ran its tests
  on 3.12 only: syntax or library behaviour that 3.12 accepts and 3.11 refuses would pass CI and
  break the shipped app. The Tests job runs on 3.11 and 3.12, the lint and the validator on 3.11.

* The JavaScript lint ran an unpinned ESLint with no config file, which stops at once, and "|| true"
  hid that: the job was green while checking nothing. It now runs a pinned ESLint with the config in
  .github/eslint over the six shell files and the installer's exe_strings.js, and a finding fails it.
* The import order check ran with no config and "|| true". It now runs a pinned isort with the
  repository's .isort.cfg over the same files as before, and a finding fails it.

Plain text checks: the CI image has no YAML library installed for the tests."""
import json
import os
import re

from conftest import ROOT

from conftest import read_source


def _step(text, name):
    """The text of one workflow step, from its name to the next step."""
    i = text.index(f"- name: {name}")
    m = re.compile(r"\n\s*- name:").search(text, i + 1)
    return text[i:m.start() if m else len(text)]


def test_the_tests_job_runs_on_the_shipped_python_and_the_next_one():
    text = read_source(".github/workflows/tests.yml")
    assert re.search(r'python-version:\s*\[\s*"3\.11",\s*"3\.12"\s*\]', text), "a matrix of 3.11 and 3.12"
    assert 'python-version: ${{ matrix.python-version }}' in _step(text, "Set up Python")


def test_the_lint_and_the_validator_run_on_the_shipped_python():
    for rel in (".github/workflows/lint-python.yml", ".github/workflows/validate-version.yml"):
        text = read_source(rel)
        assert re.search(r"python-version:\s*'3\.11'", text), rel
        assert "3.12" not in text, rel


def test_the_frontend_workflow_runs_when_a_shell_changes_and_installs_from_the_lock():
    """Four jsdom test files read the three shells' main.js, but the workflow's path filter had only
    the templates, the languages, app.py and the tests, so a shell change never ran them on its own
    push. And npm install can drift from tests/frontend/package-lock.json; npm ci cannot."""
    text = read_source(".github/workflows/frontend-tests.yml")
    for shell in ("windows/electron/**", "mac/electron/**", "linux/electron/**"):
        assert text.count(f'- "{shell}"') == 2, f"{shell} must be in the push and the pull_request paths"
    assert "npm install" not in text
    assert re.search(r"run: npm ci\b", text)
    readers = [n for n in ("backend_start", "python_missing_box", "quit_app_handler", "quit_confirm")
               if '"electron", "main.js"' in read_source(f"tests/frontend/{n}.test.mjs")]
    assert len(readers) == 4, readers


def test_the_validator_workflow_runs_when_a_file_it_checks_changes():
    """The validator checks windows/app-files.txt, the installer folder build and the language files,
    but its path filter did not list them, so a change there never ran it on its own push."""
    text = read_source(".github/workflows/validate-version.yml")
    for path in ("windows/app-files.txt", "windows/installer/**", "languages/**"):
        assert text.count(f"- '{path}'") == 2, f"{path} must be in the push and the pull_request paths"


ESLINT_DIR = ".github/eslint"
ESLINT_FILES = ("windows/electron/main.js", "windows/electron/preload.js", "mac/electron/main.js",
                "mac/electron/preload.js", "linux/electron/main.js", "linux/electron/preload.js",
                "windows/installer/exe_strings.js")
EXACT = re.compile(r"^\d+\.\d+\.\d+$")


def _eslint_lines():
    text = read_source(".github/workflows/lint-javascript.yml")
    return text, [line.strip() for line in text.splitlines() if re.search(r"\beslint\b", line)
                  and not line.strip().startswith("#") and "name:" not in line]


def test_the_javascript_lint_can_fail():
    text, lines = _eslint_lines()
    runs = [line for line in lines if "eslint.config.mjs" in line]
    assert runs, "no eslint command with the repository's config"
    assert "|| true" not in text, "a lint step that cannot fail"
    assert "npm install -g" not in text, "ESLint must come from the pinned lock, not the latest release"
    assert re.search(r"working-directory: \.github/eslint\s+run: npm ci\b", text), "npm ci in .github/eslint"
    for run in runs:
        assert run.startswith(f"{ESLINT_DIR}/node_modules/.bin/eslint -c {ESLINT_DIR}/eslint.config.mjs "), run


def test_the_javascript_lint_covers_every_shell_file_and_the_installer_script():
    _, lines = _eslint_lines()
    linted = {w for line in lines if "eslint.config.mjs" in line for w in line.split() if w.endswith(".js")}
    assert linted == set(ESLINT_FILES), sorted(linted ^ set(ESLINT_FILES))
    for rel in ESLINT_FILES:
        assert os.path.isfile(os.path.join(ROOT, rel)), rel


def test_the_eslint_config_and_its_exact_versions_are_in_the_repository():
    config = read_source(f"{ESLINT_DIR}/eslint.config.mjs")
    assert "js.configs.recommended" in config and "allowEmptyCatch: true" in config
    pkg = json.loads(read_source(f"{ESLINT_DIR}/package.json"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert set(deps) == {"eslint", "@eslint/js", "globals"}, deps
    lock = json.loads(read_source(f"{ESLINT_DIR}/package-lock.json"))
    for name, version in deps.items():
        assert EXACT.match(version), f"{name} {version} is not an exact version"
        assert lock["packages"][f"node_modules/{name}"]["version"] == version, f"the lock does not hold {name} {version}"


def test_the_javascript_lint_runs_when_what_it_checks_changes():
    text = read_source(".github/workflows/lint-javascript.yml")
    for path in ("**/electron/*.js", "windows/installer/exe_strings.js", ".github/eslint/**",
                 ".github/workflows/lint-javascript.yml"):
        assert text.count(f"- '{path}'") == 2, f"{path} must be in the push and the pull_request paths"



def _isort_step():
    return _step(read_source(".github/workflows/lint-python.yml"), "Check import sorting")


def test_the_import_order_check_can_fail():
    step = _isort_step()
    assert "|| true" not in step, "an import order check that cannot fail"
    assert "informational" not in step.lower()
    assert re.search(r"^\s+isort --check-only --diff app\.py linux/app\.py scripts/\s*$", step, re.M), step


def test_the_isort_config_and_its_exact_version_are_in_the_repository():
    config = read_source(".isort.cfg")
    assert re.search(r"^profile = black$", config, re.M) and re.search(r"^line_length = 100$", config, re.M)
    install = _step(read_source(".github/workflows/lint-python.yml"), "Install linting tools")
    assert re.search(r"\bisort==\d+\.\d+\.\d+\b", install), install
    assert not re.search(r"\bisort(?!==)\b", install.replace("isort==", "")), "isort without a pinned version"


def test_the_python_lint_runs_when_its_config_changes():
    text = read_source(".github/workflows/lint-python.yml")
    for path in ("**.py", ".isort.cfg", ".github/workflows/lint-python.yml"):
        assert text.count(f"- '{path}'") == 2, f"{path} must be in the push and the pull_request paths"
