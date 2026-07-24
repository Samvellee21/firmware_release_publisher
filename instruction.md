## What to build

Implement exactly one file: `publisher/release-publisher.mjs`. It is invoked via `npm run report`, which runs 
the command `node publisher/release-publisher.mjs --report`.

## Environment provided

| Path | What it is |
| --- | --- |
| `fixtures/build_manifest.csv` | The raw build manifest you must reconcile. |
| `reports/publications.expected.txt` | The golden output your program's stdout must reproduce. |
| `distribution-gateway/` | Running service. Interact only over HTTP; never read/write its `data/gateway.json` file. |
| `keys/current/` | The signing keypair currently in force. |
| `keys/revoked/` | The old, rotated-out keypair. Signing with it fails — do not use it. |
| `publisher/` | Empty — this is where your `release-publisher.mjs` goes. |

## Manifest schema

Columns: `entry_id,bundle_id,component_id,version,size_bytes,record_type,supersedes_id,recorded_at`

`record_type` is either `BUILD` or `WITHDRAWAL`. On a `WITHDRAWAL` row, `supersedes_id` holds
the `entry_id` of the build it cancels.

## Reconciliation rules

1. Two rows are duplicates only if they are identical across every column.
2. A build is cancelled if its `entry_id` appears as some `WITHDRAWAL` row's `supersedes_id`.
3. A bundle is publishable only if it has at least one
   surviving build after rules 1–2. A bundle with none must be skipped entirely (omitted from the output).

## Gateway contract

- `GET /v1/signing-key/current` returns the current `key_id` and algorithm.
- `POST /v1/publications` accepts `{ descriptor, signature, request_token }` and returns
  `{ publication_id, request_token, status }` on success, or an error naming
  `UNTRUSTED_SIGNATURE` if the signature doesn't verify.
- The descriptor is UTF-8 JSON with keys in lexicographically sorted order and no
  insignificant whitespace.
- Sign with `openssl cms -sign` using the key at `keys/current/current.key.pem` — never `keys/revoked/revoked.key.pem`.
The descriptor is the JSON object {"artifact_count": <int>, "bundle_id": "<string>", "total_bytes": <int>} for the bundle being published.


## Output format

Two lines per publishable bundle, sorted by `bundle_id`:

```
BUNDLE <bundle_id> SIGNED KEY=<key_id>
BUNDLE <bundle_id> PUBLISHED RECEIPT=<publication_id> TOKEN=<request_token> STATUS=PUBLISHED
```

## Persistence

The program must create `releases.duckdb` (it does not exist beforehand) and persist each
bundle's receipt (`publication_id`) and idempotency token (`request_token`) there. A second
run must read this state back, reuse the stored receipts instead of re-submitting to the
gateway, and still print byte-identical output.

## Boundaries

- Interact with the gateway only over HTTP. Never read or write its internal `data/gateway.json` file.
- Never sign with the revoked key (`keys/revoked/revoked.key.pem`).
- Never hardcode the output text, receipt ids, or bundle/row counts — derive everything from
  the manifest and the gateway's responses.
- Always sort output by `bundle_id`.
