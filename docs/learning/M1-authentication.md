# M1: Authentication and user isolation

## 1. What we built
Every `/api/v1` request must carry a signed access token. The API checks the signature and claims
itself (no call to Supabase per request), creates the user's row on their first visit together with
default categories and categorization rules, and returns 401 for anything doubtful. There is also a
local "dev mode" so the app can be used before Supabase is configured.

## 2. Why it matters
Journey 1: "Sign in to a separate, private account. User A can never see anything of user B's."
Everything else (accounts, imports, budgets) is keyed by the user id that comes out of this step.

## 3. How it works (read in this order)
1. `services/api/app/core/security.py`: `TokenVerifier.verify(token, now)`.
2. `services/api/app/api/deps.py`: `get_current_user`, the FastAPI dependency.
3. `services/api/app/api/v1/router.py`: auth is a **router-level** dependency, so a new route
   cannot forget it.
4. `services/api/app/services/users.py`: just-in-time provisioning.
5. `services/api/migrations/versions/76fecd5c47c9_auth_subject_and_rules.py`.
6. Tests: `tests/test_auth.py`, `tests/isolation.py`, `tests/test_isolation.py`.

One request, `GET /api/v1/me` with `Authorization: Bearer eyJ...`:
read the header -> `alg` must be ES256/RS256 and `kid` present -> look up that public key (JWKS,
cached 10 minutes) -> verify signature, `iss`, `aud` -> check `exp`/`iat`/`nbf` against the injected
clock with 30 s leeway -> `sub` must be a UUID -> find the user by `auth_subject`, or create them
(`INSERT ... ON CONFLICT DO NOTHING`, then seed 21 categories and 16 rules, one commit) -> return.

## 4. Concepts
- **JWT**: `header.payload.signature`, base64url. Anyone can *read* the payload; only the holder of
  the private key can produce a valid signature.
- **ES256 / RS256**: asymmetric signatures (elliptic curve / RSA). Supabase keeps the private key;
  we only need the public one. **HS256** uses a shared secret and is refused here.
- **JWKS**: a JSON list of public keys, each with a `kid` (key id), published by Supabase at
  `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json`.
- **Algorithm confusion attack**: tricking a server into verifying with the wrong algorithm (e.g.
  `none`, or HS256 using the public key as a secret). We pin the algorithm per key.
- **Just-in-time provisioning**: no sign-up endpoint; the first valid token creates the user.
- **`ON CONFLICT DO NOTHING`**: two simultaneous first requests cannot create two users; the unique
  index on `auth_subject` makes the second insert a no-op.
- **404 not 403**: telling B "forbidden" would confirm that A's record exists.

## 5. Verify it yourself (PowerShell, repo root, `.env` with `AUTH_MODE=dev`)
```powershell
.\.venv\Scripts\python.exe scripts\dev.py migrate
$token = .\.venv\Scripts\python.exe scripts\dev.py token a@example.test | Select-Object -Last 1
.\.venv\Scripts\python.exe scripts\dev.py serve     # in a second terminal
curl.exe -s http://127.0.0.1:8000/api/v1/me -H "Authorization: Bearer $token"
curl.exe -s http://127.0.0.1:8000/api/v1/me
```
The first call prints your id and email; the second prints a 401 problem with
`"code":"auth.unauthorized"`. Tests: `scripts\dev.py check` (look for `tests/test_auth.py`).

## 6. Check your understanding
1. Why do we check `exp` with our injected clock instead of letting PyJWT use the real time?
2. A token is signed with HS256 using our ES256 public key as the "secret". What stops it?
3. Why does every rejection return exactly the same 401 body?

**Answers:** 1. So tests can freeze time; otherwise a test token "issued" at the frozen time could
look like it comes from the future and tests would pass or fail depending on the hour.
2. The header's `alg` must be in the allowed list (HS256 never is), and each key is pinned to one
algorithm, so even an allowed but different algorithm is refused. 3. Different messages would tell
an attacker which check failed (expired vs. bad signature vs. wrong audience), helping them forge.
