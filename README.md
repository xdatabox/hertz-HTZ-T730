# Project Hertz task repository

This repository belongs to one task. Its name ends in your task code (for example `hertz-HTZ-T017`). You will fork it and open **three pull requests** into it over the life of the task:

| When | Pull request | Into branch | Contains | Title |
|---|---|---|---|---|
| Attempt 1 | **Codebase** | `codebase` | the one archive you will mount on the platform, nothing else | `<task_code> codebase` |
| Attempt 1 | **Attempt 1** | `main` | the `attempt1/` folder (your brief) | `<task_code> attempt1` |
| Attempt 2 | **Attempt 2** | `main` | the `attempt2/` folder (your conversation summary) | `<task_code> attempt2` |

**All three pull requests stay open until the task is delivered.** Reviewers approve or send the task back on the annotation platform and leave their feedback as comments on these pull requests. A task can come back to you even after a later review, so you always fix things by pushing to the same branch. Never close or merge your own pull requests, and do not open new ones for the same task. The project team merges them when the task is delivered.

The `codebase` branch starts **empty** on purpose. The code the model sees must never contain your brief, so the two live on separate branches. Since October 2026 the codebase pull request carries the **exact archive you will mount** (one `.zip`, `.tar` or `.tar.gz` file at the root), so what the reviewer checks and what the model gets are the same bytes; the pre-check lists what is inside, and the reviewer reads that listing. Unpacked trees pushed before that are still accepted.

Full instructions with screenshots and videos are on the project instructions page linked in your task. This is the short version.

## Why one text file per field

Everything you write in `attempt1/` and `attempt2/` is pasted into the platform exactly as it is. To copy a file: open it on GitHub and press **Copy raw file** (the copy icon above the file), then paste into the matching platform field. Line breaks and quotes come through unchanged. Do not type `\n` for a new line; press Enter. `meta.txt` is the only file you do not paste: it holds short `key: value` details for the reviewer and the check.

| File | Platform field |
|---|---|
| `attempt1/task_description.txt` | Task description |
| `attempt1/how_to_judge_completion.txt` | How to judge completion |
| `attempt1/reviewer_notes.txt` | Other notes for the reviewer (may be empty) |
| `attempt1/first_message.txt` | Describe the task… (your first message to the model) |
| `attempt1/mount_source.txt` | "Where did this file come from?", asked when you mount the zip (one line; the client reads it) |
| `attempt2/finish_notes.txt` | what you write when you finish the conversation |

## Attempt 1

**Fork and clone.** Fork this repository to your GitHub account. When GitHub asks, **untick "Copy the main branch only"** so the `codebase` branch comes with it. Clone your fork.

**Codebase pull request.**

1. Build the archive from your code, pinned to one state, with the code's own name as its single top-level folder. From a git checkout: `git archive --format=zip --prefix=<project>/ -o <project>.zip <commit>`. Code that is not in git: `zip -r <project>.zip <project>/ -x '<project>/node_modules/*' '<project>/.venv/*' '<project>/dist/*'`. Leave out build output and dependency folders (`node_modules`, `.venv`, `target`, `dist`) and the `.git` folder (the platform cannot record code changes with it inside; `git archive` never includes it); keep a `.gitignore`. Name the file after the code, never after this repository or your task code: the client sees the file name. Under 50 MB is the target; GitHub refuses files over 100 MB.
2. `git checkout codebase` (if git says the name is ambiguous because your clone has two remotes: `git checkout --track origin/codebase`; if your fork has no `codebase` branch: `git fetch https://github.com/Handshake-project-hertz/<this repository>.git codebase && git checkout -b codebase FETCH_HEAD`). Always build on this branch: GitHub refuses a pull request from a branch with no history in common with `codebase`, so do not start one with `git checkout --orphan`.
3. Copy the archive to the repository root as the only file on the branch: `git add <project>.zip && git commit -m "codebase" && git push -u origin codebase`.
4. Open a pull request from your fork's `codebase` branch **into this repository's `codebase` branch**. Title: `<task_code> codebase`. Copy the latest commit's full 40-character SHA from the pull request. Keep the file: when you mount it later, download this exact file from the pull request (open it on GitHub, **Download raw file**); do not rebuild it. The pre-check comment on your brief shows its size and checksum, which is how a reviewer confirms the platform got the same file.

**Attempt 1 pull request.**

5. `git checkout main && git checkout -b attempt1`
6. `cp -R templates/attempt1 attempt1` and fill in every file. `examples/attempt1/` is a complete example. In `attempt1/meta.txt`, put your codebase pull request URL and the commit SHA from step 4. Leave `reviewer_notes.txt` empty if you have nothing to add, but keep the file. `mount_source.txt` is one line: the real origin of the code, as the client will read it when you mount the zip. Open-source code: the upstream repository at the commit or tag (a bare URL such as `https://github.com/owner/repo/commit/<sha>`, or a sentence like the example). Your own code: a sentence such as "My own <name> project, private; exported with git archive at commit <sha>; I own the code and allow it to be shared." Never this task repository, your fork of it, a pull request, a task code, or process words such as "approved" or "session". Reviewers check this line.
7. `python3 tools/validate.py attempt1` and fix what it reports.
8. Push and open a pull request into `main`. Title: `<task_code> attempt1`.
9. Wait for the **Automated pre-check** comment. Every push gets a new one, naming the commit it checked; older ones fold away as outdated.
   - **"changes needed"**: fix the BLOCKING items in this pull request (push to the same branch) **before you submit on the platform**, and wait for the next comment. Items marked *must fix* (secrets, blocked terms, missing files, `\n` typed as text, …) have to be fixed. If you are sure an item marked *fix or explain* is wrong for your task, reply on the pull request explaining why, then submit; the reviewer reads your explanation and decides.
   - **"no blocking issues (not an approval)"**: step 1 of 2 is done. It does **not** mean your task is approved. A human reviewer reads every submission and approves it or sends it back with comments.
   - To re-run without a new commit (for example after an outage), edit the pull request description, or push an empty commit (`git commit --allow-empty -m rerun && git push`). If the check shows as failed with no log lines at all, it did not run (an organisation-side problem); tell your project lead rather than rewriting your brief.
10. Paste **both** pull request links into your task on the annotation platform and submit. **Leave both open.** The platform does not stop a submission whose pre-check is red, but the reviewer does: without a fix or an explanation for every blocking item, the task comes back to you.

## Attempt 2

1. On the annotation platform, start from the exact link in your task. Fill in the task form from the files in your attempt 1 pull request (open each file on GitHub, **Copy raw file**, paste). Mount the archive from your codebase pull request at the commit pinned in `attempt1/meta.txt`: download that exact file from GitHub (open the file in the pull request, **Download raw file**) and mount it unchanged, never GitHub's "Download ZIP" of the branch (its folder and file are named after this repository, and the client sees the file name). When the platform asks **where the file came from**, type your `attempt1/mount_source.txt` line exactly: choose **URL** when the line is only a URL, **Other** when it is a sentence. Send your first message exactly as approved.
2. Work turn by turn. Finish honestly. You may start as many conversations as you need; submit one. Copy its conversation identifier: the `taskId` in the address bar, shown again when you finish.
3. Bring your fork's `main` up to date (**Sync fork** on GitHub, then `git checkout main && git pull`), then `git checkout -b attempt2`. Branch from `main`, not from `attempt1`.
4. `cp -R templates/attempt2 attempt2` and fill it in. `examples/attempt2/` is a complete example.
5. `python3 tools/validate.py attempt2`, commit, push, open a pull request into `main`. Title: `<task_code> attempt2`. The pre-check on the pull request compares `first_message_used.txt` with the first message in your open attempt 1 pull request.
6. Paste the pull request link, the conversation identifier and your first message into your task on the platform and submit. Leave all three pull requests open.

## If your task is sent back

The reviewer's feedback is on the platform and as comments on the pull request it concerns.

- **Sent back to Attempt 1** (from any review): change the files in your open attempt 1 pull request (or your codebase pull request) and push to the same branch. If you had already finished a conversation, start a new one from the revised brief and then update your attempt 2 pull request the same way.
- **Sent back to Attempt 2**: push the changes to your open attempt 2 pull request.
- Resubmit on the platform with the same pull request links.
- **Brief filed before October 2026 as `attempt1.json` and already merged:** bring your fork's `main` up to date (**Sync fork** on GitHub, then `git checkout main && git pull`; this also gives you `templates/attempt1/`), create a new branch from it (`git checkout -b attempt1-revised`), `cp -R templates/attempt1 attempt1`, and fill the files from your old brief: copy each field's text out of `attempt1.json`, replacing every `\n` with a real line break and every `\"` with `"` (the pre-check flags any that are left); fill `meta.txt` (same codebase pull request and commit unless the reviewer asked for a code change) and the new `mount_source.txt`. Open a pull request into `main`, title `<task_code> attempt1`, and submit its link on the platform together with your codebase pull request link. The old `attempt1.json` stays on `main` and is ignored once the folder exists.

## What the pre-check enforces

- A paperwork pull request changes only the `attempt1/` folder or only the `attempt2/` folder at the root, and nothing else. Each folder holds exactly the files in its template. (`attempt1.json` / `attempt2.json` from before October 2026 are still accepted.)
- `task_code` matches this repository; minimum lengths; no template placeholders; no secrets; some terms are blocked (the check names the letter it starts with).
- No `\n` or `\"` typed as two characters outside `backticks`: that is the trace of text copied out of a JSON file, and the platform would show it.
- `codebase_pr_url` is a pull request in this repository into `codebase`, open or merged; `codebase_commit_sha` exists on it, and the tree at that commit holds exactly one readable archive (`.zip`, `.tar`, `.tar.gz`) and nothing else (unpacked trees from before October 2026 are still accepted). The archive unpacks into one top-level folder named after the code, has no `.git` folder and no Finder `__MACOSX` folder inside, and neither the file name nor the folder name names this project or a task code.
- The archive's listing contains none of this project's paperwork, template, schema or check files (your codebase's own `.github` folder is fine), preferably no dependency folders, no credential files (`.env` with values, `.netrc`, `.npmrc`, private keys, `credentials.json`, keystores) and no blocked term in a path.
- The codebase at the pinned commit is a real project: at least 10 files and 20 KB of source outside dependency folders.
- The pre-check comment names the archive, its file count, size and SHA-256 and shows its listing, so a reviewer can inspect it without unzipping and can match it to the file mounted on the platform.
- `how_to_judge_completion.txt` contains at least one command, flag, or file path a reviewer can run or open.
- The brief is not a copy of `examples/attempt1/` with light edits.
- A review model reads the brief (attempt 1 only) and blocks two clear cases: a first message that hands over the solution, and a toy task or fresh canvas. It also notes, without blocking, when a brief reads as machine-generated. If the model cannot be reached, this step reports "not run" and does not block.
- The first message never mentions the reviewer or the brief.
- `mount_source.txt` is one non-empty line that never names this project, a task repository, a fork of it or a pull request; for open-source code it names the upstream repository (*fix or explain*), ideally at a commit or tag (suggestion).
- In `attempt2/`, `first_message_used.txt` equals the approved first message unless `first_message_changed: true` in `meta.txt` with a reason in `change_reason.txt`.

Blocking items marked *fix or explain* are the judgment checks (the review model's two questions, the codebase size floor, nothing runnable in `how_to_judge_completion.txt`, similarity to the example); all other blocking items are *must fix*.

Suggestions (non-blocking) point at what a reviewer will also notice: a recipe-shaped, very short or over-long first message, a short task description, a codebase pull request that moved past the pinned commit, no recognisable project file, dependency folders left in, `.pem`/`.key` files that may be fixtures, open-source code with no LICENSE file or no upstream commit named in the notes. These checks are a floor, not the review: a human reviewer reads every submission.
