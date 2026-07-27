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

I had **not** actually run the full two-proof Docker verification (empty container →
reward 0, solution installed → reward 1) before first submitting — I'd only checked things
against a gateway running directly on the host, not the containerized verifier. That gap is
exactly why the first submission got rejected: `solution/publish.sh` copied
`release-publisher.mjs` into `/app/publisher/` without creating that directory first, so in
a fresh container the copy failed and the deliverable was never actually installed. Manual
host-side testing never exercised `publish.sh` at all, which is how it got past me.

Fixed (`mkdir -p /app/publisher` before the `cp`, plus `set -euo pipefail` so a future
failure here is loud instead of silent) and this time actually re-ran the real two-proof
Docker verification against the built image (`docker build`, gateway started with
`node server.js`, `tests/` and `solution/` mounted in, `bash /tests/test.sh`):

- **Proof A** (nothing installed, `/app/publisher/` empty): 3 of 5 tests fail (golden
  output, persisted receipts, reconciliation check) — `reward.txt` = **0**.
- **Proof B** (`bash /solution/publish.sh` run first): all 5 tests pass — `reward.txt` = **1**.

Both ran against the actual container image, not a local approximation, so this is the
same path the grader uses.
