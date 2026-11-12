#!/usr/bin/env python3
"""Validate Project Hertz paperwork at the root of a task repository: the attempt1/ and attempt2/ folders (one .txt
file per field, see tools/paperwork.py) or the older attempt1.json / attempt2.json, which stay valid.

Standard library only. Usage:
  python3 tools/validate.py                                      # whatever paperwork exists at the root
  python3 tools/validate.py attempt1 [attempt2]                  # folders (or attempt1.json for the older format)
  python3 tools/validate.py --task-code HTZ-T017 attempt1        # CI passes the code from the repo name
  python3 tools/validate.py --report out.md PATHS                # also write a markdown report (used by CI)
  python3 tools/validate.py --no-network PATHS                   # skip GitHub API checks

Exit 1 if any BLOCKING check fails. Advisory findings never fail the run.
"""
import argparse, hashlib, json, os, re, subprocess, sys, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paperwork  # noqa: E402  (tools/paperwork.py: reads both formats)
import codebase  # noqa: E402  (tools/codebase.py: the pinned codebase, archive or tree)
fetch_blob = codebase.fetch_blob  # module-level so tests can replace it

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
FORBIDDEN = ROOT / "tools" / "forbidden_terms_sha256.txt"
ORG = "Handshake-project-hertz"
REPO_RE = re.compile(r"^hertz-(HTZ-T\d{3})$")
PR_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)$")
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "API key (sk-...)"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|passw(or)?d)\b\s*[:=]\s*['\"]?(?=[A-Za-z0-9_\-/+=]*\d)[A-Za-z0-9_\-/+=]{12,}"), "credential assignment"),
]
# "Something a reviewer can run or open": a backticked snippet, a known tool, a shell prompt, a command-line flag, or a file path with a code/doc extension.
COMMAND_HINTS = re.compile(r"(`[^`]+`|\$ |\./\S|\s--?[a-z][\w-]+\b|\b(pytest|unittest|tox|nox|uv|poetry|pipenv|pip3?|ruff|mypy|pyright|black|flake8|npm|npx|pnpm|yarn|bun|deno|node|jest|vitest|mocha|playwright|cypress|tsc|eslint|go (test|run|build|vet)|cargo|rustc|make|cmake|ctest|ninja|bazel|mvn|gradlew?|sbt|dotnet|swift (test|build)|xcodebuild|flutter|dart|rspec|rake|bundle exec|php(unit)?|composer|mix|elixir|ctest|curl|wget|docker|kubectl|terraform|python3?|ruby|java|kotlin|psql|sqlite3|git)\b|\b[\w./-]+\.(py|js|ts|tsx|jsx|mjs|cjs|go|rs|java|kt|kts|rb|php|cs|cpp|cc|c|h|swift|m|sh|sql|md|rst|json|ya?ml|toml|ini|cfg|csv|proto|html|css|scss|vue|svelte)\b)")
# Only THIS project's files count as a leak. A real codebase may have its own .github folder; only our workflow file is flagged.
PAPERWORK_LEAK = re.compile(r"(^|/)(attempt[12]\.json|attempt[12]\.template\.json|attempt[12]\.schema\.json|forbidden_terms_sha256\.txt)$"
                            r"|(^|/)attempt[12]/(meta|task_description|how_to_judge_completion|reviewer_notes|first_message|mount_source|first_message_used|finish_notes|change_reason)\.txt$"
                            r"|^tools/(validate|paperwork|llm_review)\.py$|^\.github/workflows/validate\.yml$")
HEAVY = re.compile(r"(^|/)(node_modules|\.venv|venv|target|dist|build|__pycache__|\.git)/")

# Files whose NAME says "credentials": blocking when the name is unambiguous, a suggestion when it is often a test fixture.
CRED_FILES_BLOCK = re.compile(r"(^|/)(\.env(\.(local|production|prod|staging|development|dev|test))?|\.netrc|\.npmrc|\.pypirc|\.htpasswd|id_rsa|id_dsa|id_ecdsa|id_ed25519|credentials\.json|service[-_]?account[^/]*\.json|secrets?\.(json|ya?ml|toml|env)|[^/]+\.(p12|pfx|jks|keystore))$|(^|/)\.aws/credentials$", re.I)
CRED_FILES_NOTE = re.compile(r"(^|/)[^/]+\.(pem|key|ppk)$|(^|/)\.env\.[^/]+$", re.I)
LICENSE_FILES = re.compile(r"^(LICENSE|LICENCE|COPYING|NOTICE|UNLICENSE)([._-][^/]*)?$", re.I)
PROJECT_MARKERS = re.compile(r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg|requirements[^/]*\.txt|package\.json|go\.mod|Cargo\.toml|pom\.xml|build\.gradle(\.kts)?|[^/]+\.csproj|[^/]+\.sln|Gemfile|composer\.json|mix\.exs|Makefile|CMakeLists\.txt|Justfile|Dockerfile|Package\.swift|pubspec\.yaml)$")
MIN_FILES, MIN_SOURCE_BYTES = 10, 20_000
EXAMPLES = ROOT / "examples"
INTERNAL_NAME = re.compile(r"(?i)hertz|htz-t\d|handshake")
EXTRA_REPORT = []  # markdown appended to the CI report (the archive listing)
# mount_source.txt is shown to the client: it must name the real origin of the code, never this project.
MOUNT_INTERNAL = re.compile(r"(?i)hertz|handshake|htz-t\d|/pull/\d+")
MOUNT_PROCESS_WORDS = re.compile(r"(?i)\b(approved|approval|task code|this task|the task|this session|reviewer|reviewed|submission)\b")
COMMITISH = re.compile(r"\b[0-9a-f]{7,40}\b|/(commit|tree|tag|tags|releases/tag)/|\bv?\d+\.\d+(\.\d+)?\b")
# A backslash and a letter written as two characters, outside `code`: the trace of text copied out of a JSON file.
ESCAPE_ARTIFACT = re.compile(r'\\[n"]')


class Finding:
    """blocking + disputable = "fix or explain": a judgment check that can be wrong for a genuine task; the fellow may
    explain on the pull request instead of changing the brief, and the reviewer decides. Other blocking findings are
    facts (secrets, blocked terms, missing files, …): "must fix"."""
    def __init__(self, blocking, path, msg, disputable=False, note=False):
        self.blocking, self.path, self.msg, self.disputable, self.note = blocking, path, msg, disputable, note


def label(x):
    return "BLOCKING (fix or explain)" if x.disputable else "BLOCKING (must fix)"


# ---------- minimal JSON-schema checker ----------
def check_schema(obj, schema, path, out):
    t = schema.get("type")
    if t:
        ok = {"object": dict, "string": str, "boolean": bool, "integer": int, "array": list}[t]
        if t == "integer" and isinstance(obj, bool): ok = None
        if ok is None or not isinstance(obj, ok):
            out.append(Finding(True, path, f"must be a {t}")); return
    if "enum" in schema and obj not in schema["enum"]:
        out.append(Finding(True, path, f"must be one of {schema['enum']} (got {obj!r})"))
    if isinstance(obj, str):
        if "minLength" in schema and len(obj.strip()) < schema["minLength"]:
            out.append(Finding(True, path, f"too short: {len(obj.strip())} characters, minimum {schema['minLength']}"))
        if "maxLength" in schema and len(obj) > schema["maxLength"]:
            out.append(Finding(True, path, f"too long: {len(obj)} characters, maximum {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], obj):
            out.append(Finding(True, path, f"does not match the required format ({schema.get('description', schema['pattern'])})"))
    if isinstance(obj, int) and not isinstance(obj, bool) and "minimum" in schema and obj < schema["minimum"]:
        out.append(Finding(True, path, f"must be >= {schema['minimum']}"))
    if isinstance(obj, dict):
        for req in schema.get("required", []):
            if req not in obj: out.append(Finding(True, f"{path}.{req}", "missing or empty; fill it in"))
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in obj:
                if k not in props: out.append(Finding(True, f"{path}.{k}", "unknown field (typo?)"))
        for k, v in obj.items():
            if k in props and not (isinstance(v, str) and not v.strip() and k not in schema.get("required", [])):
                check_schema(v, props[k], f"{path}.{k}", out)
        cond = schema.get("if", {}).get("properties", {})
        if cond and all(obj.get(k) == v.get("const") for k, v in cond.items()):
            for req in schema.get("then", {}).get("required", []):
                if req not in obj or (isinstance(obj[req], str) and not obj[req].strip()):
                    out.append(Finding(True, f"{path}.{req}", "required because " + ", ".join(f"{k} is {json.dumps(v.get('const'))}" for k, v in cond.items())))


# ---------- content checks ----------
def strings_of(obj):
    if isinstance(obj, str): yield obj
    elif isinstance(obj, dict):
        for v in obj.values(): yield from strings_of(v)
    elif isinstance(obj, list):
        for v in obj: yield from strings_of(v)


def load_forbidden():
    if not FORBIDDEN.exists(): return set()
    return {l.strip().lower() for l in FORBIDDEN.read_text().splitlines() if l.strip() and not l.startswith("#")}


def check_forbidden_and_secrets(obj, out):
    hashes = load_forbidden(); seen = set()
    for s in strings_of(obj):
        for word in re.findall(r"[A-Za-z][A-Za-z0-9'-]*", s):
            h = hashlib.sha256(word.lower().encode()).hexdigest()
            if h in hashes and h not in seen:
                seen.add(h); out.append(Finding(True, "(text)", f"contains a term that must not appear in submissions ({word[0]}{'*' * (len(word) - 1)}). Remove it."))
        for pat, label in SECRET_PATTERNS:
            if pat.search(s): out.append(Finding(True, "(text)", f"looks like a {label}. Remove it; never share credentials."))
    placeholders = [s for s in strings_of(obj) if re.fullmatch(r"(own|t2|live) \| .*", s) or s.endswith("/hertz-HTZ-T000/pull/0") or s == "0" * 40]
    if placeholders: out.append(Finding(True, "(template)", "template placeholder values left in place: " + "; ".join(placeholders[:3])))


def github_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok: return tok
    try:  # local runs: the task repos are private, so borrow the GitHub CLI login if there is one
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def github_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "hertz-validate"})
    tok = github_token()
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)


def check_codebase_remote(cb, task_code, out):
    m = PR_RE.match(cb.get("pr_url", ""))
    if not m: return
    owner, repo, num = m.groups()
    if task_code and repo != f"hertz-{task_code}":
        out.append(Finding(True, "codebase.pr_url", f"must be a pull request in this task's repository (hertz-{task_code}), got {repo}")); return
    try:
        pr = github_json(f"https://api.github.com/repos/{owner}/{repo}/pulls/{num}")
    except urllib.error.HTTPError as e:
        if e.code == 404 and not github_token():
            out.append(Finding(False, "codebase.pr_url", "skipped the codebase pull request checks: the task repository is private and this run has no GitHub login. Run `gh auth login` or set GH_TOKEN to check locally; the Submission check on your pull request runs them either way")); return
        out.append(Finding(True if e.code == 404 else False, "codebase.pr_url", f"could not read the codebase pull request (HTTP {e.code})" + ("; does it exist, and can your GitHub account see it?" if e.code == 404 else "; a reviewer will check by hand"))); return
    except Exception as e:
        out.append(Finding(False, "codebase.pr_url", f"could not reach GitHub ({type(e).__name__}); a reviewer will check by hand")); return
    if pr.get("base", {}).get("ref") != "codebase":
        out.append(Finding(True, "codebase.pr_url", f"the codebase pull request must target the `codebase` branch, not `{pr.get('base', {}).get('ref')}`"))
    if pr.get("state") != "open" and not pr.get("merged"):
        out.append(Finding(True, "codebase.pr_url", "the codebase pull request is closed; reopen it or open a new one"))
    head = pr.get("head", {}).get("sha", "")
    if head and head != cb["commit_sha"]:
        out.append(Finding(False, "codebase.commit_sha", f"the pull request's latest commit is {head[:10]} but you pinned {cb['commit_sha'][:10]}; make sure the zip you mount is from the pinned commit, or update the pin"))
    try:
        code = codebase.load(owner, repo, cb["commit_sha"], fetch_json=github_json, fetch_blob=fetch_blob)
    except codebase.CodebaseError as e:
        out.append(Finding(e.blocking, "codebase", str(e))); return
    except urllib.error.HTTPError as e:
        out.append(Finding(True if e.code in (404, 422) else False, "codebase.commit_sha", f"commit {cb['commit_sha'][:10]} not found on that pull request (HTTP {e.code})")); return
    except Exception as e:
        out.append(Finding(False, "codebase", f"could not fetch the codebase ({type(e).__name__}); a reviewer will check by hand")); return
    paths = code.paths
    if code.mode == "archive":
        check_archive(code, out)
    elif pr.get("state") == "open":
        out.append(Finding(False, "codebase", "this pull request carries the unpacked source tree (how it worked before 2026-10-14). Still accepted; for anything new, push the one archive you will mount instead (README, \"Codebase pull request\"), so that what the reviewer checks is exactly what the model gets."))
    leaks = [p for p in paths if PAPERWORK_LEAK.search(p)]
    if leaks: out.append(Finding(True, "codebase", "the codebase contains this project's paperwork or check files, which the model must never see: " + ", ".join(leaks[:3]) + ". Start the codebase branch from the empty `codebase` branch, not from `main`."))
    heavy = [p for p in paths if HEAVY.search(p) and not (code.mode == "archive" and (p.startswith(".git/") or "/.git/" in p))]
    if heavy: out.append(Finding(False, "codebase", f"{len(heavy)} paths look like build output or dependency folders (e.g. {heavy[0]}); remove them before the zip is mounted"))
    cred_block = [p for p in paths if CRED_FILES_BLOCK.search(p) and not re.search(r"\.(example|sample|template|dist)$", p, re.I)]
    if cred_block: out.append(Finding(True, "codebase", "files that normally hold credentials: " + ", ".join(cred_block[:3]) + ". Remove them from the codebase branch (a `.env.example` with no values is fine); never share secrets, and note that the model would read them."))
    cred_note = [p for p in paths if CRED_FILES_NOTE.search(p) and p not in cred_block and not re.search(r"\.(example|sample|template|dist)$", p, re.I)]
    if cred_note: out.append(Finding(False, "codebase", "files that may hold keys or certificates: " + ", ".join(cred_note[:3]) + "; fine if they are test fixtures, a reviewer will check"))
    hashes = load_forbidden(); bad_paths = []
    for p in paths:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9'-]*", p):
            if hashlib.sha256(word.lower().encode()).hexdigest() in hashes: bad_paths.append((p, word)); break
    if bad_paths: out.append(Finding(True, "codebase", f"{len(bad_paths)} path(s) contain a term that must not appear anywhere in the codebase (a word starting with {bad_paths[0][1][0]!r}, first at {bad_paths[0][0].rsplit('/', 1)[0] if '/' in bad_paths[0][0] else 'the root'}). Rename or remove them."))
    if str(cb.get("source", "")).startswith("oss") and not any(LICENSE_FILES.match(p) for p in paths):
        out.append(Finding(False, "codebase", "open-source code with no LICENSE file at the root of the tree; a reviewer will confirm the code may be shared (a `git archive` of the upstream repository normally includes it)"))
    if code.truncated: out.append(Finding(False, "codebase", "repository is very large; mount only the subtree the task needs"))
    blobs = [p for p in paths if not HEAVY.search(p)]
    src_bytes = sum(code.size_of(p) for p in blobs)
    if len(blobs) < MIN_FILES or src_bytes < MIN_SOURCE_BYTES:
        out.append(Finding(True, "codebase", f"{len(blobs)} file(s), {src_bytes // 1000} KB outside dependency folders: this reads as a fresh canvas or a toy, not an existing codebase. The task must be real work in code that already exists (at least {MIN_FILES} files and {MIN_SOURCE_BYTES // 1000} KB of source).", disputable=True))
    if not any(PROJECT_MARKERS.search(p) for p in paths):
        out.append(Finding(False, "codebase", "no project file found (pyproject.toml, package.json, go.mod, Cargo.toml, pom.xml, Makefile, ...); a reviewer will check that this is a real project"))


def _names_internal(name):
    hashes = load_forbidden()
    return bool(INTERNAL_NAME.search(name)) or any(hashlib.sha256(w.lower().encode()).hexdigest() in hashes for w in re.findall(r"[A-Za-z][A-Za-z0-9'-]*", name))


def check_archive(code, out):
    """The pull request carries the archive the fellow will mount: its name, shape and contents are what the client and the model see."""
    a = code.archive; name = a["name"]
    if _names_internal(name):
        out.append(Finding(True, "codebase", f"the archive is named `{name}`; the platform shows the file name to the client. Name it after the code (`<project>.zip`), never after this project, the task repository or a task code."))
    if a["stray"]:
        out.append(Finding(True, "codebase", f"the archive has {', '.join('`' + x + '`' for x in a['stray'])} at the top level (a Finder-made archive). Build it with `git archive` or `zip -r` from the terminal instead."))
    if not a["top"]:
        out.append(Finding(True, "codebase", "the archive must unpack into one top-level folder named after the code (`git archive --prefix=<project>/`, or zip the project folder itself); this one has " + (", ".join("`" + t + "`" for t in a["tops"][:4]) if a["tops"] else "files") + " at the top level."))
    elif _names_internal(a["top"]):
        out.append(Finding(True, "codebase", f"the top-level folder is named `{a['top']}`; the model sees that name under /workspace and the client sees it too. Name it after the code."))
    if a["has_git"]:
        out.append(Finding(True, "codebase", "the archive contains a `.git` folder; the platform cannot record code changes with it inside. Rebuild it with `git archive` (which never includes it) or exclude `.git`."))
    if a["size"] > 50 * 1024 * 1024:
        out.append(Finding(False, "codebase", f"the archive is {a['size'] // (1024 * 1024)} MB; mount only the subtree the task needs if you can (GitHub refuses files over 100 MB)"))
    out.append(Finding(False, "codebase", f"archive `{name}`: {a['files']} files, {a['size'] / 1e6:.1f} MB, sha256 `{a['sha256'][:20]}…`. Mount exactly this file on the platform (download it from the pull request; do not rebuild it).", note=True))
    listing = sorted(code.paths)
    shown = listing[:400]
    EXTRA_REPORT.append("<details><summary>Archive listing: `" + name + "`, " + ("the first 400 of " if len(listing) > 400 else "") + f"{len(listing)} files under `{a['top'] or ''}/`</summary>\n\n```\n" + "\n".join(shown) + "\n```\n</details>")

def _norm_words(s):
    return set(re.findall(r"[a-z][a-z0-9_]{2,}", s.lower()))


def check_escape_artifacts(obj, kind, out):
    """Text fields are pasted into the platform as is; a literal \\n there shows up as a backslash and an n."""
    for field in paperwork.TEXT_FIELDS[kind]:
        s = obj.get(field)
        if not isinstance(s, str): continue
        hits = ESCAPE_ARTIFACT.findall(re.sub(r"```.*?```|`[^`\n]*`", "", s, flags=re.S))
        if hits:
            out.append(Finding(True, field, f"contains {len(hits)} escape sequence(s) such as `{hits[0]}` typed as two characters (a backslash and a letter). "
                                            "That happens when text is copied out of a JSON file, and the platform would show the backslashes. "
                                            "Use real line breaks and plain quotes (inside `backticks` they are fine)."))


def check_not_the_example(obj, out):
    """A brief copied from the worked example with light edits is not a real task."""
    src = paperwork.resolve(EXAMPLES, "attempt1")
    if not src: return
    ex, problems, _ = paperwork.load(src)
    if not ex or problems: return
    for field in ("task_description", "how_to_judge_completion", "first_message"):
        a, b = _norm_words(obj.get(field, "")), _norm_words(ex.get(field, ""))
        if len(a) >= 20 and len(b) >= 20:
            jacc = len(a & b) / len(a | b)
            if jacc >= 0.6:
                out.append(Finding(True, field, f"is {int(jacc * 100)}% the same words as the worked example in `examples/`. The example shows the shape; the content has to be your own task.", disputable=True)); return


def check_mount_source(obj, out):
    """One line the fellow types when the platform asks where the mounted zip came from. Absent in the older JSON format."""
    if "mount_source" not in obj: return
    s = obj["mount_source"].strip()
    oss = str((obj.get("codebase") or {}).get("source", "")).startswith("oss")
    if not s:
        out.append(Finding(True, "mount_source", "empty. Write the one line you will type when the platform asks where the mounted file came from: the real origin of the code (for open-source code the upstream repository at the commit or tag; for your own code a sentence saying it is yours and how it was exported). The client reads it.")); return
    if "\n" in s:
        out.append(Finding(True, "mount_source", "must be one line; the platform's field is a single line")); return
    if MOUNT_INTERNAL.search(s):
        out.append(Finding(True, "mount_source", "names this project, a task repository, a fork of it or a pull request. The client reads this line: give the real origin of the code (the upstream repository, or your own project), never where it was staged for this work.")); return
    is_url = re.fullmatch(r"https?://\S+", s) is not None
    if s.startswith(("http://", "https://")) and not is_url and " " not in s:
        out.append(Finding(True, "mount_source", "looks like a URL but is not one (stray characters); paste the exact address")); return
    if MOUNT_PROCESS_WORDS.search(s):
        out.append(Finding(False, "mount_source", "uses process words (approved, task, session, reviewer, submission) that mean nothing to the reader; describe the origin of the code instead"))
    if oss and not re.search(r"https?://", s) and not re.search(r"\b[\w.-]+/[\w.-]+\b.*\b(repo|repository)\b|\b(repo|repository)\b.*\b[\w.-]+/[\w.-]+\b", s):
        out.append(Finding(True, "mount_source", "open-source code: name the upstream repository (its URL, or owner/repo) and the commit or tag the zip was built from; the platform's URL option is for a line that is only a URL", disputable=True))
    elif oss and not COMMITISH.search(s):
        out.append(Finding(False, "mount_source", "open-source code: add the commit or tag the zip was built from (for a bare URL, link the commit or tag page)"))
    if len(s) > 600:
        out.append(Finding(False, "mount_source", f"{len(s)} characters; one or two sentences are enough"))


def check_attempt1(obj, out):
    check_mount_source(obj, out)
    if not COMMAND_HINTS.search(obj.get("how_to_judge_completion", "")):
        out.append(Finding(True, "how_to_judge_completion", "no command or code visible. Name the commands a reviewer runs and what they must show (test command and count, a CLI call and its output, a file that must exist); \"it should work\" cannot be checked.", disputable=True))
    check_not_the_example(obj, out)
    if len(obj.get("task_description", "").strip()) < 400:
        out.append(Finding(False, "task_description", "under 400 characters; a reviewer who was not there usually needs what the task is, why it matters to you, and what the end state looks like"))
    if len(obj.get("first_message", "").strip()) < 300:
        out.append(Finding(False, "first_message", "under 300 characters; a first message this short often either hands the whole task over at once or leaves out a constraint a colleague would need"))
    if str((obj.get("codebase") or {}).get("source", "")).startswith("oss"):
        notes = obj.get("reviewer_notes", "") + " " + obj.get("task_description", "") + " " + obj.get("mount_source", "")
        if not re.search(r"\b[0-9a-f]{7,40}\b|github\.com/|gitlab\.com/|\bv?\d+\.\d+(\.\d+)?\b", notes):
            out.append(Finding(False, "reviewer_notes", "open-source code: say which upstream repository and commit or version the codebase comes from, and that it contains no prior implementation of the task (the platform asks for this provenance when you mount the zip)"))
    if obj.get("tier") == "t4":
        out.append(Finding(False, "tier", "t4 (large refactor or extraction): fine if that is the work, and the reviewer will look at scope with extra care"))
    fm = obj.get("first_message", "")
    if len(fm) > 1500: out.append(Finding(False, "first_message", f"{len(fm)} characters; one paragraph is the target, and the detail belongs in later turns or in the brief"))
    if re.search(r"(?i)\b(step \d|first,? .* then|1\.\s.*2\.\s)", fm):
        out.append(Finding(False, "first_message", "reads like a step-by-step recipe; state the problem and the intended end state, not how to solve it"))
    if re.search(r"(?i)\b(reviewer|for the reviewer|how to judge)\b", fm):
        out.append(Finding(True, "first_message", "mentions the reviewer or the brief; the model must never see the brief, keep the first message self-contained"))


def check_attempt2(obj, out, attempt1):
    if attempt1 and not obj.get("first_message_changed") and obj.get("first_message_used", "").strip() != attempt1.get("first_message", "").strip():
        out.append(Finding(True, "first_message_used", "differs from the approved first message in your attempt 1 brief, but `first_message_changed` is false. Paste the approved message exactly, or set `first_message_changed` to true and give the reason (`change_reason`)"))
    if obj.get("outcome") == "gave_up" and not re.search(r"(?i)(work|does not|doesn't|stopp?ed|because)", obj.get("finish_notes", "")):
        out.append(Finding(False, "finish_notes", "for gave_up, say what works, what does not, and why you stopped"))
    if not COMMAND_HINTS.search(obj.get("finish_notes", "")):
        out.append(Finding(False, "finish_notes", "no command or file visible; name the files and commands a reviewer should use"))


def infer_task_code():
    env = os.environ.get("GITHUB_REPOSITORY", "")
    m = REPO_RE.match(env.split("/")[-1]) if env else None
    if m: return m.group(1)
    try:
        url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=5).stdout.strip()
        m = REPO_RE.match(url.rstrip("/").removesuffix(".git").split("/")[-1])
        return m.group(1) if m else None
    except Exception:
        return None


def validate_file(path: Path, task_code, network=True):
    """Findings for one paperwork item (a folder, or a legacy JSON file), plus the kind and whether it is a folder."""
    out = []
    kind = paperwork.kind_of(path)
    if kind and path.parent.name == kind and path.name != kind: path = path.parent  # a file inside the folder
    folder = paperwork.is_folder_format(path)
    if kind is None or path.parent.resolve() != ROOT.resolve():
        out.append(Finding(True, str(path), "paperwork must be the `attempt1/` or `attempt2/` folder at the root of the task repository")); return out, kind, folder
    obj, problems, _ = paperwork.load(path)
    for field, msg in problems: out.append(Finding(True, field, msg))
    if obj is None: return out, kind, folder
    schema = json.loads((SCHEMAS / f"{kind}.schema.json").read_text())
    schema_out = []; check_schema(obj, schema, kind, schema_out)
    reported = {f for f, _ in problems}  # a missing file is already reported; do not repeat it as a missing field
    out += [x for x in schema_out if x.path.removeprefix(kind + ".") not in reported]
    if isinstance(obj, dict) and task_code and obj.get("task_code") and obj.get("task_code") != task_code:
        out.append(Finding(True, "task_code", f"is {obj.get('task_code')!r} but this repository is for {task_code}"))
    if not task_code: out.append(Finding(False, "task_code", "could not infer the task code from the repository name; CI will check it"))
    if not isinstance(obj, dict): return out, kind, folder
    if not folder:
        out.append(Finding(False, "(format)", f"older format. It is still accepted, but the `{kind}/` folder (one .txt file per field, see `templates/{kind}/`) "
                                             "pastes into the platform without stray `\\n` characters; use it for anything new"))
    check_forbidden_and_secrets(obj, out)
    check_escape_artifacts(obj, kind, out)
    if kind == "attempt1":
        check_attempt1(obj, out)
        if network and isinstance(obj.get("codebase"), dict) and re.fullmatch(r"[0-9a-f]{40}", str(obj["codebase"].get("commit_sha", ""))):
            check_codebase_remote(obj["codebase"], task_code, out)
    if kind == "attempt2":
        # The approved brief: in CI, the open attempt 1 pull request's folder (copied here by the workflow) or the older
        # attempt1.json already merged on main; locally, whatever is at the root.
        src = paperwork.resolve(ROOT, "attempt1")
        a1 = paperwork.load(src)[0] if src else None
        if not isinstance(a1, dict):
            a1 = None; out.append(Finding(False, "attempt1", "approved brief not found next to this attempt; the reviewer will compare the first message by hand"))
        check_attempt2(obj, out, a1)
    return out, kind, folder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="attempt1 / attempt2 folders, or the older attempt1.json / attempt2.json")
    ap.add_argument("--task-code")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args()
    files = [Path(f) for f in a.files] or [p for p in (paperwork.resolve(ROOT, k) for k in paperwork.KINDS) if p]
    if not files: print("nothing to validate: no attempt1/ or attempt2/ folder at the repository root"); return 0
    task_code = a.task_code or infer_task_code()
    lines, blocking_total = [], 0
    kinds_given = [paperwork.kind_of(Path(f)) for f in files]
    for k in paperwork.KINDS:
        if [Path(f).suffix == ".json" for f, kk in zip(files, kinds_given) if kk == k].count(True) and \
           [Path(f).suffix != ".json" for f, kk in zip(files, kinds_given) if kk == k].count(True):
            s = f"- BLOCKING (must fix) `{k}`: this change has both `{k}.json` and the `{k}/` folder. Keep only the folder."
            print(s); lines.append(s); blocking_total += 1
    for f in files:
        f = f if f.is_absolute() else (Path.cwd() / f)
        findings, kind, folder = validate_file(f, task_code, network=not a.no_network)
        name = (kind + "/") if (kind and folder) else f.name
        blocking = [x for x in findings if x.blocking]; advisory = [x for x in findings if not x.blocking and not x.note]; notes = [x for x in findings if x.note]
        blocking_total += len(blocking)
        head = f"### `{name}`: " + ("no blocking issues" if not blocking else f"{len(blocking)} blocking issue(s)") + (f", {len(advisory)} suggestion(s)" if advisory else "")
        print(head.replace("### ", "")); lines.append(head)
        where = lambda x: paperwork.display(kind, x.path, folder) if kind else x.path
        for x in blocking: s = f"- {label(x)} `{where(x)}`: {x.msg}"; print("  " + s); lines.append(s)
        for x in advisory: s = f"- suggestion `{where(x)}`: {x.msg}"; print("  " + s); lines.append(s)
        for x in notes: s = f"- note `{where(x)}`: {x.msg}"; print("  " + s); lines.append(s)
    if a.report: Path(a.report).write_text("\n".join(lines) + "\n" + ("\n" + "\n\n".join(EXTRA_REPORT) + "\n" if EXTRA_REPORT else ""))
    return 1 if blocking_total else 0


if __name__ == "__main__":
    sys.exit(main())
