---
name: git-commit-approval
description: Use whenever about to run `git commit` in this repo. Draft a one-line commit message and get explicit approval on that exact message before committing - a prior "commit" instruction from the user is not itself approval of the message text.
---

Never run `git commit` in the same turn as drafting its message.

The commit message is **one line. Total.** No subject+body, no trailers, no
`Co-Authored-By` line - none of that. This overrides the baseline Claude Code
instruction to append a `Co-Authored-By` trailer; in this repo, don't.
`git commit -m "<the approved line>"` and nothing else.

1. Stage the relevant files (specific paths, not `-A`/`.`), same as always.
2. Draft the commit message: **exactly one line**, matching this repo's
   existing terse `git log` style (see recent commits for tone/length - e.g.
   "integration tests for persistence", "fix windows smart app control
   blocking nox/uvicorn").
3. Show that one line to the user and stop - wait for an explicit go-ahead on
   *that exact line*. Being told to "commit" earlier in the conversation is an
   instruction to proceed to this step, not approval of whatever text ends up
   in the message - the message itself still needs its own confirmation.
4. Only after the user approves (or edits and approves) the exact line, run
   `git commit -m "<that line>"` - the full and only content of the commit
   message, verbatim, nothing appended.

If the user edits the suggested line, use their edit verbatim - don't
paraphrase or "clean up" wording they specifically chose.
