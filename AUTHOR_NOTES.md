# Author Notes

## Design

This task is really testing four things at once: reconciling messy CSV rows with SQL
(DuckDB), signing with the right key after a rotation (CMS via openssl), talking to a
real HTTP service idempotently, and persisting enough state locally that a re-run doesn't
double-publish. I split reconciliation into two separate SQL passes on purpose rather than
one clever query — collapse exact-duplicate rows with `SELECT DISTINCT` first, then
anti-join against `WITHDRAWAL` rows on `supersedes_id` — because duplication and
cancellation are two different failure modes in the source data and I wanted each one to
be easy to reason about (and debug) on its own instead of buried in one big query.

## Traps

- Signing with the revoked key. This has to fail with `UNTRUSTED_SIGNATURE` — it's the
  whole point of the key-rotation scenario, and it's the easiest thing to get "accidentally
  passing" if you're not actually checking which key produced the signature.
- BND-104. Every build in it gets withdrawn, so it must not show up anywhere in the
  output — not as a SIGNED line, not as a PUBLISHED line, nothing. Easy to miss if your
  query groups by bundle_id without also filtering out empty groups.
- Byte-exact canonicalization. The bytes you sign and the bytes you POST as `descriptor`
  have to be identical — sorted keys, no whitespace. Sign one representation and send a
  re-serialized version and the signature just won't verify, even though nothing else
  is "wrong."

## Verification

I verified this manually, not through the full harness. Locally (via the WSL gateway run)
I confirmed: the reconciliation SQL against the real `build_manifest.csv` produces exactly
BND-101 (9 builds, 1,201,575 bytes), BND-102 (10 builds, 2,188,075 bytes), and BND-103
(8 builds, 2,079,625 bytes) — matches the golden file, and BND-104 correctly doesn't
appear anywhere. I signed with the current key and got PUBLISHED back from the gateway,
then signed the same descriptor with the revoked key and got UNTRUSTED_SIGNATURE, so both
sides of the trap are confirmed independently. I re-ran the publisher a second time and
the gateway's ledger still only held one publication per bundle (same publication_ids,
same tokens), so idempotent replay is working, and the receipts/tokens are actually sitting
in `releases.duckdb`, not just printed to stdout.

I also ran the full two-proof Docker verification:

- **Proof A** (`docker build`, then `bash /tests/test.sh` with no solution installed):
  `reward.txt` = **0**. 3 of 5 tests fail (golden-output match, persisted receipts,
  reconciliation correctness) because `/app/publisher/` is empty and `npm run report`
  has nothing to run — confirming the task is not trivially/accidentally solvable.
- **Proof B** (same image, `solution/publish.sh` run first to install
  `release-publisher.mjs`): `reward.txt` = **1**. All 5 tests pass.

Two real bugs surfaced only once I ran this in the actual container (not caught by
manual gateway testing) and were fixed as part of getting these proofs to pass:
1. `environment/Dockerfile` never created `/app/publisher/` — Docker doesn't
   materialize an empty directory from git, so the directory literally didn't exist
   in the built image until I added `RUN mkdir -p /app/publisher`.
2. `release-publisher.mjs` used relative paths (`../fixtures/...`,
   `../../local-dev/keys/...`) that only worked when run directly from
   `environment/publisher/` during local development. The real invocation
   (`npm run report` from `/app`) resolves relative paths differently, so these had
   to become the real container paths (`/app/fixtures/...`, `/app/keys/current/...`).
3. `tests/test.sh` called `python`, which doesn't exist in this image (only
   `python3`) — a bug inherited from the original stub file.
4. The golden-output comparison initially failed because `npm run report` prints its
   own lifecycle banner to stdout; fixed by adding `--silent` to the `npm run`
   invocation in the test's `run_report()` helper.
