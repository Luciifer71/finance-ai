# Prompts for Claude Code

Open a terminal in `C:\Users\Krish\finance-ai`, start Docker Desktop, then run `claude`.
Select the model with `/model` before sending the first prompt.

## 1. Kickoff prompt (first session)

```
You are the backend engineer for Finance AI, my private iPhone-first personal finance app. I am
Krishay, the backend owner; my partner builds the mobile app and you must not touch her part.

Read these files completely before doing anything else, in this order:
1. CLAUDE.md
2. docs/handoff/BACKEND_HANDOFF.md (the specification and milestone plan; it is the source of truth)
3. docs/handoff/PROGRESS.md
4. docs/handoff/HUMAN_TODO.md
5. docs/adr-0002-ledger-data-model.md, then skim services/api (app, tests, migrations)

Then:
- Verify the environment: Docker Postgres is up, the venv at the repo root works, and the existing
  test suite passes against 127.0.0.1. Record the result in PROGRESS.md (Evidence log).
- Write the M0 task checklist into PROGRESS.md.
- Build milestones M0 through M13 in order, exactly as the handoff describes, following the Git and
  PR workflow in section 15 and the MERGE_POLICY in PROGRESS.md.

Working rules:
- Work autonomously. Do not ask me questions unless section 17 ("When to stop") applies. For
  anything that needs me but does not block you, add it to HUMAN_TODO.md and keep going.
- Financial correctness, user isolation and privacy come before speed and before feature breadth.
- Every money rule in section 6 gets tests with hand-calculated expected values.
- Run the full check before every commit. Never weaken a check to make it pass.
- Update PROGRESS.md after every completed task so a fresh session could resume from it alone.
- Write the learning note for each milestone (section 16). I want to understand everything you build.
- Check current official documentation for anything version-dependent (FastAPI, SQLAlchemy, PyJWT,
  Supabase Auth) instead of relying on memory.

When your context gets long, finish the current task, make sure PROGRESS.md is current, and continue.
Start now.
```

## 2. Resume prompt (any later session, or after you stopped Claude Code)

```
Resume work on the Finance AI backend. Read CLAUDE.md, docs/handoff/PROGRESS.md and
docs/handoff/HUMAN_TODO.md, then the sections of docs/handoff/BACKEND_HANDOFF.md for the current
milestone. Check `git status` and `git log --oneline -10` on the current branch and any open PRs
(`gh pr list`) to confirm the real state matches PROGRESS.md; if they differ, trust Git and fix
PROGRESS.md. Then continue from the next unfinished task, following the same rules as before.
Work autonomously until M13 is done or section 17 says to stop.
```

## 3. If you finished something in HUMAN_TODO.md

```
I finished these items in docs/handoff/HUMAN_TODO.md: <list them>. <Details, for example: the
redacted CSV is at C:\Users\Krish\Downloads\statement_redacted.csv>. Tick them, use them where the
handoff says, record it in PROGRESS.md, then resume the plan.
```

## 4. Review prompt (ask Claude Code to teach you a milestone)

```
Walk me through milestone M<N> as if I am reviewing the PR. Start from docs/learning/M<N>-*.md, then
show me the 5 most important pieces of code in reading order and explain each in simple language:
what it does, why it is written that way, and what would break without it. Then ask me the three
questions from the learning note one at a time and check my answers.
```
