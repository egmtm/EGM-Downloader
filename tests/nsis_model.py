"""A small interpreter for the parts of windows/setup.nsi that decide what happens to a folder.

It runs the statements the installer's logic is made of (LogicLib If blocks on FileExists, DirState
and registers, StrCpy, Delete, RMDir, MessageBox with its silent default and jumps, Abort, Quit,
Call, nsExec, ExecWait, the registry writes and deletes) over a model of the folder: a set of paths
such as "$INSTDIR/resources/app.asar". It stops at the first statement that writes the new files
(SetOutPath or File), so a run tells what was refused, closed, asked and deleted before the copy.

Only the statements the script uses are understood; anything else is an error, so a change to the
script that the model cannot follow fails the tests instead of being skipped."""
import fnmatch
import re

from conftest import read_source

NSI = read_source("windows/setup.nsi")


def section(name, text=NSI):
    start = text.index(f'Section "{name}"')
    return text[start:text.index("SectionEnd", start)]


def function(name, text=NSI):
    start = text.index(f"Function {name}\n")
    return text[start:text.index("FunctionEnd", start)]


def macro(name, text=NSI):
    m = re.search(rf"^!macro {re.escape(name)}\b[^\n]*\n(.*?)^!macroend", text, re.M | re.S)
    assert m, f"macro {name} not found"
    return m.group(1)


def statements(text):
    """Logical statements: continuation lines joined, comments and blank lines dropped."""
    out, buf = [], ""
    for line in text.splitlines():
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        s = (buf + line).strip()
        buf = ""
        if s and not s.startswith(";"):
            out.append(s)
    return out


def expand(text, macros=("EGM_REMOVE_OLD_LAYOUT",), extra=None):
    """Replace '!insertmacro NAME' of the listed macros by their bodies (extra: name -> body)."""
    bodies = {m: macro(m) for m in macros}
    bodies.update(extra or {})
    out = []
    for s in statements(text):
        m = re.match(r"!insertmacro (\w+)$", s)
        if m and m.group(1) in bodies:
            out.extend(statements(bodies[m.group(1)]))
        else:
            out.append(s)
    return out


def _norm(path):
    return path.replace("\\", "/")


class Run:
    """One run of a list of statements.

    folder:   set of file paths ("$INSTDIR/..."; other roots allowed); changed in place
    silent:   /S: every MessageBox takes its /SD answer
    answers:  the answers to the boxes otherwise ("IDOK", "IDCANCEL", "IDYES", "IDNO"), in order
    running:  process ids that EGM_FindRunning reports; a taskkill of them stops them unless
              they are in `unkillable`
    arch:     the facts the architecture check reads: {"IsNativeAMD64": True, ...}
    regs:     starting registers and variables ({"$PreviousVersion": "1.5.2.3", ...})
    exec_exit: the exit code ExecWait reports
    registry: set of "KEY/VALUE" names present; changed in place
    """

    def __init__(self, folder, *, silent=True, answers=(), running=(), unkillable=(), arch=None,
                 regs=None, exec_exit=0, registry=None, defines=None):
        self.folder = folder
        self.silent = silent
        self.answers = list(answers)
        self.running = set(running)
        self.unkillable = set(unkillable)
        self.arch = arch or {"IsNativeAMD64": True, "IsNativeARM64": False, "AtLeastWin11": True}
        self.regs = dict(regs or {})
        self.exec_exit = exec_exit
        self.registry = registry if registry is not None else set()
        self.defines = {"APPNAME": "EGM Downloader", "VERSION": "9.9.9.9", "REGKEY": "Software\\EGM Downloader",
                        "UNINSTREG": "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\EGMDownloader"}
        self.defines.update(defines or {})
        self.boxes, self.calls, self.execs, self.deleted = [], [], [], []
        self.outcome = "end"          # "end", "aborted", "quit" or "writes"
        self.finds = 0

    # ── values ────────────────────────────────────────────────────────────────
    def sub(self, s):
        s = re.sub(r"\$\{(\w+)\}", lambda m: self.defines.get(m.group(1), m.group(0)), s)
        for k in sorted(self.regs, key=len, reverse=True):
            s = s.replace(k, str(self.regs[k]))
        return s

    def value(self, tok):
        tok = tok.strip()
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'`":
            tok = tok[1:-1]
        return self.sub(tok)

    def exists(self, pattern):
        p = _norm(self.sub(pattern))
        if p.endswith("/*.*"):
            base = p[:-4]
            return any(f.startswith(base + "/") for f in self.folder)
        return p in self.folder or any(f.startswith(p + "/") for f in self.folder)

    def cond(self, text):
        text = text.strip()
        m = re.match(r'\$\{FileExists\}\s+(".*?")$', text)
        if m:
            return self.exists(self.value(m.group(1)))
        m = re.match(r"\$\{(IsNativeAMD64|IsNativeARM64|IsNativeIA32|AtLeastWin11|Silent)\}$", text)
        if m:
            return self.silent if m.group(1) == "Silent" else bool(self.arch.get(m.group(1)))
        m = re.match(r"(\S+|\".*?\")\s*(==|!=|>|<)\s*(\S+|\".*?\")$", text)
        if m:
            a, op, b = self.value(m.group(1)), m.group(2), self.value(m.group(3))
            if op in (">", "<"):
                ai = int(a) if re.fullmatch(r"-?\d+", a) else 0
                bi = int(b) if re.fullmatch(r"-?\d+", b) else 0
                return ai > bi if op == ">" else ai < bi
            return (a.lower() == b.lower()) == (op == "==")
        raise AssertionError(f"condition the model does not know: {text}")

    # ── running ───────────────────────────────────────────────────────────────
    def run(self, stmts):
        frames = []

        def active():
            return all(f["parent"] and f["cur"] and not f["taken"] for f in frames) if frames else True

        i = 0
        while i < len(stmts):
            s = stmts[i]
            i += 1
            m = re.match(r"\$\{(If|IfNot|AndIf|AndIfNot|OrIf|OrIfNot|ElseIf|Else|EndIf)\}\s*(.*)$", s)
            if m:
                kind, rest = m.groups()
                if kind in ("If", "IfNot"):
                    parent = active()
                    c = self.cond(rest) if parent else False
                    frames.append({"parent": parent, "taken": False, "cur": c != (kind == "IfNot")})
                elif kind in ("AndIf", "AndIfNot"):
                    f = frames[-1]
                    f["cur"] = f["cur"] and (self.cond(rest) != (kind == "AndIfNot"))
                elif kind in ("OrIf", "OrIfNot"):
                    f = frames[-1]
                    f["cur"] = f["cur"] or (self.cond(rest) != (kind == "OrIfNot"))
                elif kind == "ElseIf":
                    f = frames[-1]
                    f["taken"] = f["taken"] or f["cur"]
                    f["cur"] = self.cond(rest)
                elif kind == "Else":
                    f = frames[-1]
                    f["taken"] = f["taken"] or f["cur"]
                    f["cur"] = True
                else:
                    frames.pop()
                continue
            if re.match(r"^\w+:$", s) or not active():
                continue
            jump = self.step(s)
            if jump == "stop":
                return self
            if jump:
                i = next(k for k in range(i, len(stmts)) if stmts[k] == f"{jump}:") + 1
        return self

    def step(self, s):
        m = re.match(r'(Delete|RMDir /r|RMDir)\s+("[^"]+")$', s)
        if m:
            op, target = m.group(1), _norm(self.value(m.group(2)))
            before = set(self.folder)
            if op == "Delete":
                folder, pattern = target.rsplit("/", 1)
                self.folder -= {p for p in self.folder if p.rsplit("/", 1)[0] == folder
                                and fnmatch.fnmatchcase(p.rsplit("/", 1)[1], pattern)}
            elif op == "RMDir /r":
                self.folder -= {p for p in self.folder if p.startswith(target + "/") or p == target}
            self.deleted.extend(sorted(before - self.folder))
            return None
        if re.match(r"(SetOutPath|File)\b", s):
            self.outcome = "writes"
            return "stop"
        if s == "Abort" or s.startswith("Abort "):
            self.outcome = "aborted"
            return "stop"
        if s == "Quit":
            self.outcome = "quit"
            return "stop"
        if s.startswith("MessageBox "):
            text = re.search(r'"([^"]*)"', s).group(1)
            sd = re.search(r"/SD (ID\w+)", s)
            answer = sd.group(1) if self.silent else self.answers.pop(0)
            self.boxes.append((text, answer))
            after = s[sd.end():] if sd else s
            for btn, label in re.findall(r"\b(ID\w+)\s+(\w+)", after):
                if btn == answer:
                    return label
            return None
        m = re.match(r"StrCpy (\$\w+) (.+)$", s)
        if m:
            self.regs[m.group(1)] = self.value(m.group(2))
            return None
        m = re.match(r'\$\{DirState\}\s+("[^"]+")\s+(\$\w+)$', s)
        if m:
            base = _norm(self.value(m.group(1)))
            self.regs[m.group(2)] = 1 if any(p.startswith(base + "/") for p in self.folder) else 0
            return None
        m = re.match(r"Call (\S+)$", s)
        if m:
            self.calls.append(m.group(1))
            if m.group(1).endswith("EGM_FindRunning"):
                self.finds += 1
                self.regs["$0"] = len(self.running)
                self.regs["$1"] = " ".join(f"/PID {p}" for p in sorted(self.running))
                return None
            raise AssertionError(f"call the model does not know: {s}")
        m = re.match(r"nsExec::Exec(?:ToStack)?\s+(.+)$", s)
        if m:
            cmd = self.value(m.group(1))
            self.execs.append(cmd)
            if "taskkill.exe" in cmd:
                pids = {int(p) for p in re.findall(r"/PID (\d+)", cmd)}
                self.running -= pids - self.unkillable
            self.regs["$0"] = 0
            return None
        m = re.match(r"ExecWait\s+('[^']*'|\"[^\"]*\")(?:\s+(\$\w+))?$", s)
        if m:
            self.execs.append(self.value(m.group(1)))
            if m.group(2):
                self.regs[m.group(2)] = self.exec_exit
            return None
        m = re.match(r'WriteReg(?:Str|DWORD|ExpandStr)\s+HKCU\s+("[^"]+")\s+("[^"]+")\s+(.+)$', s)
        if m:
            self.registry.add(f"{self.value(m.group(1))}/{self.value(m.group(2))}")
            return None
        m = re.match(r'DeleteRegValue\s+HKCU\s+("[^"]+")\s+("[^"]+")$', s)
        if m:
            self.registry.discard(f"{self.value(m.group(1))}/{self.value(m.group(2))}")
            return None
        m = re.match(r'DeleteRegKey\s+(/ifempty\s+)?HKCU\s+("[^"]+")$', s)
        if m:
            key = self.value(m.group(2))
            if not m.group(1):
                self.registry -= {r for r in self.registry if r.startswith(key + "/")}
            return None
        if re.match(r"(Section|SectionEnd|Function|FunctionEnd|Pop|Sleep|DetailPrint|ReadRegStr|SectionGetSize|System::Call|CreateDirectory|"
                    r"CreateShortcut|!insertmacro MUI_LANGDLL_DISPLAY)\b", s):
            return None
        raise AssertionError(f"statement the model does not know: {s}")
