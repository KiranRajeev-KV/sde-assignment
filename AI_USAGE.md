# AI Usage Disclosure

AI tools are allowed. We want to know **how** you used them, because using them well is a
skill. Honest answers are never held against you. Discovering undisclosed use is.

## Tools used
- **Claude Code** for code, tests and docs.
- Agent skills from [`mattpocock/skills`](https://github.com/mattpocock/skills), which give Claude a
  fixed way of working: `grilling`, `domain-modeling`, `to-spec`, `to-tickets`, `implement`, `tdd` and
  `code-review`.

## What I used them for

Claude helped me write the code, tests and docs.

1. **Settling the design.** Claude questioned me on each open point in the assignment. My answers
   became the glossary entries, the seven ADRs and the decisions table. (grill-with-docs skill)
2. **Planning.** Claude turned those decisions into a spec and 14 small tickets.
3. **Building.** For each ticket, Claude wrote the tests first (some were suggested by me, and some were edge cases Claude found on its own and ran by me first). The code was written by me, by Claude, or by us together, depending on its importance and complexity. Then Claude ran the suite and reviewed the change against each ticket.
4. **Measuring and writing up.** Claude profiled the large dataset, wrote `bench.py`, and drafted SUBMISSION.md and this file.

## What I wrote or decided myself
The engineering judgement throughout the project was mine.

The architecture and major design decisions were all made by me using the grill-with-docs skill.
The data models and schema design were written and implemented by me. I also looked at the possible access patterns before writing the data models.
The design for PII redaction was my own. I used AI to write the HMAC and encryption functions.
Some of the rules were written manually by me, along with their edge-case tests.

## Where the AI was wrong or unhelpful
Claude wanted to write a lot of test cases that were not really relevant. They covered edge cases that will never occur in the real functioning of this project.

## How I verified AI-generated code
- **Tests.** There are 60 of them:
  - one per rule
  - one per tricky scenario
  - properties checked on two generated datasets: re-runs change nothing, drop-by-drop matches all-at-once, the counters add up, and no phone or name appears in the database
- **A clean clone.** Claude followed the run steps in SUBMISSION.md exactly in a fresh clone. They produced the five reports, a re-run gave identical files, and the tests passed.
- **A review on every ticket**, checking the change against what the ticket asked for.
- **Manual code review.** I read, understood and verified the codebase like a normal human.
