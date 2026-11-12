#!/usr/bin/env python3
"""Read Project Hertz paperwork in either of its two formats. Standard library only.

Current format: one folder per attempt at the repository root, one plain-text file per field, so a fellow can open a
file on GitHub, press "Copy raw file", and paste it into the platform with its line breaks intact:

  attempt1/meta.txt                      key: value lines (task_code, tier, watching_mode, codebase_*)
  attempt1/task_description.txt          free text, pasted into the platform as is
  attempt1/how_to_judge_completion.txt
  attempt1/reviewer_notes.txt            may be empty
  attempt1/first_message.txt
  attempt1/mount_source.txt          one line: the answer to the platform's "Where did this file come from?" (client-visible)

  attempt2/meta.txt                      task_code, conversation_id, first_message_changed, outcome, flags_count
  attempt2/first_message_used.txt
  attempt2/finish_notes.txt
  attempt2/change_reason.txt             only when first_message_changed is true

Legacy format: attempt1.json / attempt2.json at the root (JSON escapes line breaks as \\n, which fellows then pasted
into the platform). Briefs submitted that way stay valid.

load(path) returns (obj, problems): obj has the same shape as the legacy JSON, so the JSON schemas and every check
apply unchanged; problems are blocking format errors as (field, message) pairs.
"""
import json, re
from pathlib import Path

KINDS = ("attempt1", "attempt2")
TEXT_FIELDS = {
    "attempt1": ("task_description", "how_to_judge_completion", "reviewer_notes", "first_message", "mount_source"),
    "attempt2": ("first_message_used", "finish_notes", "change_reason"),
}
OPTIONAL_TEXT = {"attempt1": (), "attempt2": ("change_reason",)}
# meta.txt key -> location in the object (a dotted path)
META_KEYS = {
    "attempt1": {"task_code": "task_code", "tier": "tier", "watching_mode": "watching_mode",
                 "codebase_pr_url": "codebase.pr_url", "codebase_commit_sha": "codebase.commit_sha",
                 "codebase_source": "codebase.source"},
    "attempt2": {"task_code": "task_code", "conversation_id": "conversation_id",
                 "first_message_changed": "first_message_changed", "outcome": "outcome", "flags_count": "flags_count"},
}
META = "meta.txt"


def folder_files(kind):
    """Every file name allowed inside the attempt folder."""
    return {META} | {f + ".txt" for f in TEXT_FIELDS[kind]}


def read_text(p: Path) -> str:
    """UTF-8 with or without a BOM (Windows Notepad), any line ending, surrounding blank lines and spaces dropped."""
    s = p.read_bytes().decode("utf-8-sig")
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


def kind_of(path: Path):
    """'attempt1' / 'attempt2' for attempt1.json, attempt1/, attempt1/<file>.txt; None otherwise."""
    name = path.name
    if name in ("attempt1.json", "attempt2.json"): return name[:-5]
    if name in KINDS: return name
    if path.parent.name in KINDS: return path.parent.name
    return None


def is_folder_format(path: Path) -> bool:
    return path.suffix != ".json"


def resolve(root: Path, kind: str):
    """The paperwork of one kind at the repository root: the folder if it exists, else the legacy JSON, else None."""
    d, j = root / kind, root / f"{kind}.json"
    if d.is_dir(): return d
    if j.is_file(): return j
    return None


def _set(obj, dotted, value):
    keys = dotted.split(".")
    for k in keys[:-1]: obj = obj.setdefault(k, {})
    obj[keys[-1]] = value


def _parse_meta(text, kind, problems):
    out, seen = {}, set()
    allowed = META_KEYS[kind]
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"): continue
        if ":" not in line:
            problems.append(("meta", f"line {n} is not `key: value`: {line.strip()[:60]!r}")); continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key not in allowed:
            problems.append(("meta", f"line {n}: unknown key `{key}` (typo?); the keys are " + ", ".join(f"`{k}`" for k in allowed))); continue
        if key in seen:
            problems.append(("meta", f"line {n}: `{key}` appears twice")); continue
        seen.add(key)
        if value == "": continue  # left empty: reported by the schema as a missing field
        if key == "first_message_changed":
            low = value.lower()
            value = True if low in ("true", "yes") else False if low in ("false", "no") else value
        elif key == "flags_count" and re.fullmatch(r"\d+", value):
            value = int(value)
        _set(out, allowed[key], value)
    return out


def load_folder(d: Path, kind: str):
    problems, obj = [], {}
    if not d.is_dir():
        return None, [(kind, f"`{kind}/` folder not found")]
    entries = sorted(d.iterdir(), key=lambda p: p.name)
    allowed = folder_files(kind)
    for p in entries:
        if p.name not in allowed:
            what = "a folder" if p.is_dir() else "a file"
            problems.append((f"{kind}/{p.name}", f"{what} that does not belong in `{kind}/`; the folder holds only " + ", ".join(f"`{f}`" for f in sorted(allowed)) + ". Remove it (a stray `.DS_Store` counts)."))
    names = {p.name for p in entries if p.is_file()}
    if kind == "attempt1": obj["codebase"] = {}  # so an empty codebase_* key is reported by its own name
    if META not in names:
        problems.append(("meta", f"`{kind}/{META}` is missing"))
    else:
        obj.update(_parse_meta(read_text(d / META), kind, problems))
    for field in TEXT_FIELDS[kind]:
        f = field + ".txt"
        if f in names:
            obj[field] = read_text(d / f)
        elif field not in OPTIONAL_TEXT[kind]:
            problems.append((field, f"`{kind}/{f}` is missing (it may be empty only where the template says so)"))
    return obj, problems


def load(path: Path):
    """(obj, problems, kind) for attempt1.json / attempt2.json / attempt1/ / attempt2/ (or a file inside the folder)."""
    path = Path(path)
    kind = kind_of(path)
    if kind is None:
        return None, [(str(path), "not a paperwork path: expected attempt1/ or attempt2/ (or the older attempt1.json / attempt2.json)")], None
    if path.parent.name in KINDS and path.name not in KINDS: path = path.parent
    if is_folder_format(path):
        obj, problems = load_folder(path, kind)
        return obj, problems, kind
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), [], kind
    except Exception as e:
        return None, [(path.name, f"not valid JSON: {e}")], kind


def display(kind: str, field: str, folder: bool) -> str:
    """Where a finding points, in the words of the format the fellow used."""
    f = field.removeprefix(kind + ".") if field.startswith(kind + ".") else field
    if not folder:
        return f
    if f in TEXT_FIELDS[kind]: return f"{kind}/{f}.txt"
    if f == "meta": return f"{kind}/{META}"
    for key, dotted in META_KEYS[kind].items():
        if f == dotted: return f"{kind}/{META} {key}"
    return f
