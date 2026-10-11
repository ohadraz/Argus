Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel,
answering, understanding, narration and relay, e2e.

## 1. Kernel

- [x] 1.1 Event `QuestionAnswered(message, answer)`, round-tripping through the
      event log (D4)

## 2. Answering (D2)

- [x] 2.1 `agent_intent.answering`: the opening holds the question as written
      and the timeline one line per event - time, who, text
- [x] 2.2 The brief: answer from the lines only, say when they do not hold it,
      never promise an action
- [x] 2.3 The answer is the one field of a forced `submit_answer` call; asked at
      most twice; `None` when it cannot be read

## 3. Understanding (D3, D6)

- [x] 3.1 A question is answered from the incident's narrated timeline, then
      recorded as understood, then `MessageUnderstood` and `QuestionAnswered`
      are published, in that order
- [x] 3.2 A question the model cannot answer is answered with the fixed line,
      with a warning
- [x] 3.3 A question on an ended incident is answered; nothing else happens
      for any meaning but a question
- [x] 3.4 `watching` wires the timeline reader and the answering call

## 4. Narration and relay (D5)

- [x] 4.1 `QuestionAnswered` narrated as the Intent Agent's line, the answer
      whole
- [x] 4.2 The relay follows it into the thread

## 5. e2e and recording (D7)

- [x] 5.1 `scripts/record_classification.py` records an answer against an
      incident's timeline
- [x] 5.2 e2e case: a question in the thread gets an answer posted in it (user
      writes it)
- [x] 5.3 Record `intent-question` (user runs; cents)

## 6. Close

- [x] 6.1 `docs/spec-and-architecture.md` §7.5a: the intent agent answers
      questions
- [x] 6.2 Cleanup: comments, docstrings, jargon, logs and docs aligned; no test
      missing, redundant or weak; design and specs match what was built
- [x] 6.3 Module suites, typecheck, lint, guard_layering green
- [x] 6.4 `e2e_replay(mode='both')` green, in the background
- [ ] 6.5 Specs synced on archive
