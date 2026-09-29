---
name: hand-apply-edit-format
description: Use before sending any message that asks the user to apply an edit by hand - anything under tests/, argus_testkit, anthropic_double or slack_double. Covers how an edit location is addressed so the link selects the right thing, and the script that checks the draft before it is sent.
---

Claude cannot write to `tests/`, `modules/argus_testkit/`, `modules/anthropic_double/`
or `modules/slack_double/`, so every change there is a message the user pastes
in by hand. The message is only as good as its addresses.

## Check the draft before sending it

There is a Stop hook that enforces all of this, but it reads the message out of
the transcript - so it can only speak *after* the message has been shown, and
the correction then costs the user a second copy of instructions they have
already begun applying. Do not use it as the check.

Write the draft to the scratchpad and run:

```
uv run python scripts/check_edit_message.py <draft>
```

Exit 0 means it is fit to send. Otherwise it prints one complaint per line
against the files on disk. Fix the draft and run it again. Send nothing that
has not come back clean.

## The anchor is what matters, not the verb

ADD, INSERT, REPLACE, DELETE - any of them. What the rule is about is what the
link **selects** when the user clicks it, and renaming the verb to get past a
complaint is not a fix.

| Directive | What the link must select |
| --- | --- |
| ADD / INSERT | the line the pasted text lands on |
| REPLACE | exactly the text being replaced |
| DELETE | exactly what is being deleted |

Never a gap between two lines, never the neighbour of the place with the
arithmetic left to the reader.

The editor resolves `#LX-LY` with **the end exclusive**, so a range written as
the lines it names selects one line short and silently leaves the last line
behind. Replacing lines 101-104 is `#L101-L105`; replacing the single line 870
is `#L870-L871`; adding at line 273 is `#L273`.

## The rest of the rules

- **Every location is a clickable link.** Never a bare `file.py:293`, never a
  line number said in prose with no link on it.
- **The link text says which lines**, because the label is the half a reader
  sees. `[test_gating.py, lines 606-611](path#L606-L612)`, not
  `[test_gating.py](path#L606-L612)` with the range in the prose beside it.
- **Several edits to one file are listed bottom-up** - highest line number
  first - so applying one never shifts the lines of the ones still to come.
- **Re-read the numbers off disk with `grep -n` immediately before writing**,
  and again before any correction. If the user has already applied part of an
  earlier message the numbers have moved, and the right correction may be
  nothing at all.
- **Propose the whole file when the change is not tiny and precisely located.**
  A set of "add this after line 40" instructions is how a test file quietly
  ends up not saying what either party thinks it says.

## When a message has already been sent and was wrong

Do not restate the set - the user ends up with two copies and applies one
twice. Send a short correction naming only what was wrong and only the
locations that change, still bottom-up, still checked by the script first.

## Verify what landed

A hand-applied edit can be applied partly, twice, or with a line duplicated by
the paste. After the user says it is in, run the tests and `grep -n` the call
sites rather than assuming - a duplicated comment line and a missed edit have
both happened here, and both were found this way.
