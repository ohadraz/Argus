---
name: "Handover"
description: "Write a context handover document to .claude/HANDOVER.md for the next session"
category: Workflow
tags: [workflow, context, handover]
---

Generate a complete context handover document for the next session.

1. Create or update the file `.claude/HANDOVER.md`.
2. Include:
   - **Current Goal / Objective**: What we are building or fixing.
   - **Key Decisions Made**: Architectural choices, patterns, or rules agreed upon.
   - **Files Modified / Work Done**: Concise summary of what has been changed so far.
   - **Next Steps / Pending Tasks**: Exactly what needs to be done next.
3. Keep it brief, structured, and focused so it can be easily read back after a `/clear`.
4. Inform me when the file is saved so I can run `/clear`.
