## What this is

A read-only legibility pass. **No existing file is modified** — this PR only adds
`LEGIBILITY.md`, and it is trivially deletable. Close it and nothing else changes.

### Why

A census of 100 fleet repos (`SuperInstance/quilt-research-canons/projects/fleet-legend/`)
graded every repo against five obligations. This one already passes entry (L1, L2); it
fails the two that only cost something once a reader is already inside:

- **L4 — what this does NOT do.** Missing in 55 of 100 repos.
- **L5 — what to do when it fails.** Missing in 59 of 100 repos.

### What is in here, and where each line came from

5 finding(s), each read out of the repository and each carrying its evidence. Nothing
is inferred from the README, because the README is the thing being fixed.

| finding | evidence |
|---|---|
| A CI workflow exists (2 file(s), e.g. `.github/workflows/ci-python.yml`), but which events it runs on and what it actually executes are decided inside that file, not here | `.github/workflows/ci-python.yml` exists in the tree |
| It ships 4 test file(s) (e.g. `tests/test_config_wizard.py`); what runs them is not recorded anywhere in the tree | `tests/test_config_wizard.py` and 3 other path(s) match the test pattern |
| It carries a license (`LICENSE`) | `LICENSE` |
| 3+ source file(s) declare themselves incomplete, so parts of the surface are not finished — `standalone/chat.py`: *files = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md", "TODO.md",*; `standalone/start.py`: *The agent reads NEXT-ACTION.md, does the task, updates TODO.md, commits.*; `standalone/onboard.py`: *TODO.md → what to do* | read from the files named above |
| Error-raising calls are not collected in one place: 2 call sites appear across 16 files (`tests/test_git_agent.py`:156; `tests/test_github_fleet.py`:148). Nothing in the repository treats them as a set, so a reader who hits one has to grep for it | read 16 of 39 (a sample, so this is a lower bound) source file(s) in the tree; grep: `raise|throw|panic!|log.Fatal|process.exit` |

### What we deliberately did NOT write

- **Failure modes (L5).** 2 error-raising call sites exist in the source (16 of 39 (a sample, so this is a lower bound) file(s) read), but the *message a user sees* and *what to do about each one* are not derivable from a file listing. Write the two or three that actually happen. A human has to supply these; guessing them is how a completer invents a failure mode.

A completer that invents a receipt or a failure mode produces a confident lie, and a
confident lie is worse than a blank space, because a reader cannot tell it from a real
limitation. Where a fact was not derivable, this file says so instead of filling the gap.

### If you want to accept part of this

Take the table and ignore the rest. Every row is a predicate over the file listing or over
named source lines, so disagreeing with a row costs you one `ls` or one `grep` — say so in
a review comment and the line gets corrected or dropped.

Reviewed with tooling from `SuperInstance/quilt-research-canons/projects/fleet-legend/`.
