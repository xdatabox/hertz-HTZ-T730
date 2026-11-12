#!/usr/bin/env python3
"""The codebase a fellow pinned: the files the model will see. Standard library only.

A codebase pull request (into the task repository's `codebase` branch) comes in one of two shapes:

  archive (since 2026-10-14): the tree at the pinned commit holds exactly one file, the archive the fellow will mount
      on the platform (`<project>.zip`, `.tar`, `.tar.gz` or `.tgz`), and nothing else. The blob is downloaded (GitHub
      serves blobs up to 100 MB), hashed and LISTED; nothing is extracted or executed.
  tree (older submissions): the unpacked source files; the API tree listing is the entry list.

load(owner, repo, sha) -> Codebase. Raises CodebaseError (with .blocking) for a shape that cannot be checked.
"""
import hashlib, io, json, os, re, subprocess, tarfile, urllib.error, urllib.request, zipfile

ARCHIVE_RE = re.compile(r"\.(zip|tar|tar\.gz|tgz)$", re.I)
MAX_ENTRIES = 60_000
STRAY_ROOT = {"__MACOSX", ".DS_Store", "Thumbs.db"}


class CodebaseError(Exception):
    def __init__(self, msg, blocking=True):
        super().__init__(msg); self.blocking = blocking


class Codebase:
    def __init__(self, mode, paths, sizes, truncated=False, archive=None):
        self.mode, self.paths, self.sizes, self.truncated, self.archive = mode, paths, sizes, truncated, archive

    def size_of(self, path):
        return int(self.sizes.get(path) or 0)


def github_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok: return tok
    try:  # local runs: the task repos are private, so borrow the GitHub CLI login if there is one
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def _request(url, accept):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "hertz-validate"})
    tok = github_token()
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    return urllib.request.urlopen(req, timeout=120)


def github_json(url):
    with _request(url, "application/vnd.github+json") as r: return json.load(r)


def fetch_blob(owner, repo, blob_sha):
    """Raw bytes of a blob (up to GitHub's 100 MB blob limit)."""
    with _request(f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}", "application/vnd.github.raw+json") as r:
        return r.read()


def _clean(name):
    name = name.replace("\\", "/")
    while name.startswith("./"): name = name[2:]
    return name.strip("/")


def list_archive(name, data):
    """[(path, size, is_dir)] for a zip or tar given as bytes; never extracts."""
    entries = []
    low = name.lower()
    try:
        if low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for i, zi in enumerate(zf.infolist()):
                    if i >= MAX_ENTRIES: break
                    entries.append((_clean(zi.filename), zi.file_size, zi.is_dir()))
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
                for i, ti in enumerate(tf):
                    if i >= MAX_ENTRIES: break
                    entries.append((_clean(ti.name), ti.size, ti.isdir()))
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as e:
        raise CodebaseError(f"`{name}` cannot be read as an archive ({type(e).__name__}); rebuild it with `git archive` or `zip -r`")
    return [e for e in entries if e[0]]


def from_archive(name, data):
    entries = list_archive(name, data)
    files = [(p, s) for p, s, d in entries if not d]
    if not files: raise CodebaseError(f"`{name}` contains no files")
    bad = [p for p, _, _ in entries if p.startswith("/") or ".." in p.split("/")]
    if bad: raise CodebaseError(f"`{name}` contains unsafe paths (absolute or with `..`), for example `{bad[0]}`; rebuild it from inside the project folder")
    tops = sorted({p.split("/", 1)[0] for p, _, _ in entries} - STRAY_ROOT)
    stray = sorted({p.split("/", 1)[0] for p, _, _ in entries} & STRAY_ROOT)
    top = tops[0] if len(tops) == 1 and all(p == tops[0] or p.startswith(tops[0] + "/") for p, _, _ in entries if p.split("/", 1)[0] not in STRAY_ROOT) and any(p.startswith(tops[0] + "/") for p, _, _ in entries) else None
    rel = [(p.split("/", 1)[1] if top and p.startswith(top + "/") else p, s) for p, s in files if p.split("/", 1)[0] not in STRAY_ROOT]
    rel = [(p, s) for p, s in rel if p]
    has_git = any(p == ".git" or p.startswith(".git/") or "/.git/" in p for p, _ in rel)
    archive = {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "top": top, "tops": tops, "stray": stray,
               "entries": len(entries), "files": len(rel), "has_git": has_git, "truncated": len(entries) >= MAX_ENTRIES}
    return Codebase("archive", [p for p, _ in rel], dict(rel), truncated=archive["truncated"], archive=archive)


def load(owner, repo, sha, fetch_json=github_json, fetch_blob=fetch_blob):
    """The codebase at a pinned commit, whichever shape it has. HTTP errors from fetch_json propagate."""
    tree = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
    blobs = [t for t in tree.get("tree", []) if t.get("type") == "blob"]
    if not blobs: raise CodebaseError("the pinned commit has no files; the codebase branch is still empty")
    archives = [b for b in blobs if "/" not in b["path"] and ARCHIVE_RE.search(b["path"])]
    if archives:
        if len(blobs) > 1:
            others = [b["path"] for b in blobs if b not in archives][:3] or [b["path"] for b in archives[1:]][:3]
            raise CodebaseError(f"the codebase pull request must contain only the one archive you will mount; it also has {', '.join('`' + o + '`' for o in others)}. Remove everything else.")
        b = archives[0]
        if int(b.get("size") or 0) > 100 * 1024 * 1024:
            raise CodebaseError(f"`{b['path']}` is {int(b['size']) // (1024 * 1024)} MB; GitHub serves files up to 100 MB. Strip dependency and build folders, or mount only the subtree the task needs.")
        try:
            data = fetch_blob(owner, repo, b["sha"])
        except urllib.error.HTTPError as e:
            raise CodebaseError(f"could not download `{b['path']}` (HTTP {e.code}); a reviewer will check by hand", blocking=False)
        return from_archive(b["path"], data)
    return Codebase("tree", [b["path"] for b in blobs], {b["path"]: int(b.get("size") or 0) for b in blobs}, truncated=bool(tree.get("truncated")))
