# Things only Krishay can do

Claude Code: add items here instead of stopping. Never ask for secrets in chat or commit them.
Krishay: tick items as you finish them and tell Claude Code in your next prompt.

## Before or during the build (nothing here blocks Claude Code; it uses dev auth and synthetic data)
- [ ] **Create a Supabase project** (free plan) and switch on email sign-in. Make sure it uses the new
      asymmetric **JWT signing keys**. Put these in your local `.env` (never in Git):
      `AUTH_MODE=jwks`, `AUTH_JWKS_URL=https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json`,
      `AUTH_ISSUER=https://<project-ref>.supabase.co/auth/v1`, `AUTH_AUDIENCE=authenticated`.
      Share the project URL and anon key with your partner for the mobile app.
- [ ] **Get one real statement CSV** from your own bank, **redact it** (replace names, account
      numbers, UPI ids, reference numbers; keep the exact column headers, date format and layout),
      and give it to Claude Code to verify the `generic_indian_bank_v1` profile. Never commit the
      unredacted file.
- [ ] Protect `main` on GitHub: Settings > Branches > add rule for `main`: require a pull request and
      require status checks "API checks / test" and "Secret scanning" to pass.
- [ ] Make sure the GitHub CLI is installed and logged in (`gh auth status`) so Claude Code can open
      and merge PRs.

## After the build
- [ ] Read the learning notes in `docs/learning/` and the PRs; ask about anything unclear.
- [ ] Choose hosting for the beta so the iPhones can reach the API (it needs HTTPS). Candidates:
      Supabase Postgres for the database plus a small container host for the API and worker.
      Compare current free tiers before deciding.
- [ ] Run `scripts/dev.py demo` yourself on a clean database.
- [ ] Review `docs/handoff/PROGRESS.md` for open blockers, then tag `v0.1-private-beta`.

## Added by Claude Code
(Claude Code appends new items here with the date and the reason.)
