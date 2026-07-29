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

`tests/test_outputs.py` recomputes the correct `(bundle_id -> artifact_count, total_bytes)`
mapping directly from `fixtures/build_manifest.csv` at test time (same SQL shape,
independently written) rather than asserting against hardcoded literals, so a solution
can't pass by faking numbers — it has to actually reconcile correctly.

## Traps

- Signing with the revoked key. This has to fail with `UNTRUSTED_SIGNATURE` — it's the
  whole point of the key-rotation scenario, and it's the easiest thing to get "accidentally
  passing" if you're not actually checking which key produced the signature.
- BND-104. Every build in it gets withdrawn, so it must not show up anywhere in the
  output — not as a SIGNED line, not as a PUBLISHED line, nothing. Easy to miss if your
  query groups by bundle_id without also filtering out empty groups. Covered by its own
  dedicated test (`test_fully_withdrawn_bundle_is_excluded`), not just an aggregate count.
- Byte-exact canonicalization. The bytes you sign and the bytes you POST as `descriptor`
  have to be identical — sorted keys, no whitespace. Sign one representation and send a
  re-serialized version and the signature just won't verify, even though nothing else
  is "wrong."

## Verification

### Manual checks (host-side, before containerizing)

Reconciliation SQL against the real `build_manifest.csv` produces exactly BND-101
(9 builds, 1,201,575 bytes), BND-102 (10 builds, 2,188,075 bytes), and BND-103 (8 builds,
2,079,625 bytes) — matches the golden file, and BND-104 correctly doesn't appear anywhere.
Signing with the current key returns PUBLISHED; signing the same descriptor with the
revoked key returns UNTRUSTED_SIGNATURE. Re-running the publisher a second time leaves the
gateway's ledger with exactly one publication per bundle (same `publication_id`s, same
tokens) — idempotent replay works, and receipts/tokens are persisted in `releases.duckdb`,
not just printed to stdout.

### The two proofs, run in a freshly built container (not a local approximation)

```
cd environment && docker build -t task-img .
```

**Proof A — nothing installed, `/app/publisher/` empty:**

```
docker run --rm -v "$PWD/../tests":/tests:ro task-img \
  bash -c 'node /app/distribution-gateway/server.js & sleep 1; bash /tests/test.sh; cat /logs/verifier/reward.txt'

...
FAILED ../tests/test_outputs.py::test_report_output_matches_golden
FAILED ../tests/test_outputs.py::test_receipts_persisted_in_duckdb
FAILED ../tests/test_outputs.py::test_reconciliation_is_correct
FAILED ../tests/test_outputs.py::test_fully_withdrawn_bundle_is_excluded
PASSED ../tests/test_outputs.py::test_no_bundle_signed_with_revoked_key
PASSED ../tests/test_outputs.py::test_rerun_is_idempotent
4 failed, 2 passed in 2.43s

--- reward.txt ---
0
```

**Proof B — `solution/publish.sh` run first to install the reference solution:**

```
docker run --rm -v "$PWD/../tests":/tests:ro -v "$PWD/../solution":/solution:ro task-img \
  bash -c 'node /app/distribution-gateway/server.js & sleep 1; bash /solution/publish.sh && bash /tests/test.sh; cat /logs/verifier/reward.txt'

collected 6 items
../tests/test_outputs.py ......                                          [100%]
PASSED ../tests/test_outputs.py::test_report_output_matches_golden
PASSED ../tests/test_outputs.py::test_no_bundle_signed_with_revoked_key
PASSED ../tests/test_outputs.py::test_receipts_persisted_in_duckdb
PASSED ../tests/test_outputs.py::test_rerun_is_idempotent
PASSED ../tests/test_outputs.py::test_reconciliation_is_correct
PASSED ../tests/test_outputs.py::test_fully_withdrawn_bundle_is_excluded
6 passed in 4.22s

--- reward.txt ---
1
```

0 without the solution, 1 with it — both demonstrated in a clean, freshly built container.

### What went wrong on the first two submissions, and what I changed

**Submission 1** was rejected because `solution/publish.sh` copied `release-publisher.mjs`
into `/app/publisher/` without creating that directory first — in a fresh container the
copy failed silently and the deliverable was never actually installed. I'd only tested
against a gateway running directly on the host, never the real containerized install path,
so I never caught it. Fixed: `mkdir -p /app/publisher` before the `cp`, plus
`set -euo pipefail` so a future failure here is loud instead of silent.

**Submission 2** was rejected with "`tests/test_outputs.py` ... was not found," which didn't
match what I could verify externally (`git clone`, `raw.githubusercontent.com` returning
HTTP 200, and the GitHub contents API all confirmed the file was committed and public on
`main`). While investigating I found a real, reproducible bug regardless of whether it was
the exact cause: `tests/test.sh` and `solution/release-publisher.mjs` had CRLF line endings
mixed into the committed content (confirmed via `git add --renormalize` producing a real
diff, and via `git show HEAD:... | wc -c` not matching the working-copy byte count). CRLF
breaks bash (`syntax error near unexpected token 'fi'`) when the script runs inside the
Linux container — a plausible way for a grader to crash before ever reporting a normal
pass/fail. Fixed with `.gitattributes` (`* text=auto eol=lf`) and a renormalize, verified
with `git grep -Il $'\r'` returning nothing.

While re-reading `SUBMISSION_HANDBOOK.md` after that rejection, I also found and fixed:
- `instruction.md` used paths relative to `/app` instead of the absolute paths the handbook
  requires — rewritten throughout.
- `tests/test_outputs.py` asserted against hardcoded literals (`(9, 1201575)`, `== 3`)
  instead of recomputing the expected answer from the raw manifest — a solution could have
  passed those specific assertions without doing real reconciliation. Rewritten to derive
  the expected bundle set from `fixtures/build_manifest.csv` at test time.
- Several process/scaffolding files (`_skeleton.md`, `_originality_note.md`,
  `completion_plan.{md,yaml}`, `scaffold_plan.yaml`) were still tracked in the repo. They
  aren't part of the six required parts and read like tooling output rather than my own
  authoring notes, so I removed them rather than risk them being mistaken for
  non-original material.
