import duckdb from 'duckdb';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

function all(connection, sql) {
    return new Promise((resolve, reject) => {
        connection.all(sql, (err, rows) => {
            if (err) reject(err);
            else resolve(rows);
        });
    });
}

function run(connection, sql) {
    return new Promise((resolve, reject) => {
        connection.run(sql, (err) => {
            if (err) reject(err);
            else resolve();
        });
    });
}

const db = new duckdb.Database('releases.duckdb');
const con = db.connect();

await run(con, "CREATE OR REPLACE TABLE manifest AS SELECT * FROM read_csv_auto('/app/fixtures/build_manifest.csv', header=true)");

const bundles = await all(con, `
SELECT
  bundle_id,
  COUNT(*) AS artifact_count,
  SUM(size_bytes) AS total_bytes
FROM (
  SELECT b.*
  FROM (SELECT DISTINCT * FROM manifest) b
  WHERE b.record_type = 'BUILD'
    AND NOT EXISTS (
      SELECT 1
      FROM (SELECT DISTINCT * FROM manifest) w
      WHERE w.record_type = 'WITHDRAWAL'
        AND w.supersedes_id = b.entry_id
    )
) survivors
GROUP BY bundle_id
ORDER BY bundle_id
`);

const keyResp = await fetch('http://127.0.0.1:7070/v1/signing-key/current');
const keyMeta = await keyResp.json();

for (const bundle of bundles) {
    const descriptor = `{"artifact_count":${bundle.artifact_count},"bundle_id":"${bundle.bundle_id}","total_bytes":${bundle.total_bytes}}`;

    fs.writeFileSync('descriptor.bin', descriptor);
    execFileSync('openssl', [
        'cms', '-sign', '-in', 'descriptor.bin',
        '-signer', '/app/keys/current/current.cert.pem',
        '-inkey', '/app/keys/current/current.key.pem',
        '-outform', 'PEM', '-binary', '-out', 'sig.pem',
    ]);
    const signature = fs.readFileSync('sig.pem', 'utf8');

    const requestToken = `token-${bundle.bundle_id}`;

    const resp = await fetch('http://127.0.0.1:7070/v1/publications', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ descriptor, signature, request_token: requestToken }),
    });
    const receipt = await resp.json();

    await run(con, `
    CREATE TABLE IF NOT EXISTS publications (
        bundle_id VARCHAR PRIMARY KEY,
        key_id VARCHAR,
        artifact_count INTEGER,
        total_bytes INTEGER,
        request_token VARCHAR,
        publication_id VARCHAR,
        status VARCHAR
    )
    `);

    await run(con, `DELETE FROM publications WHERE bundle_id = '${bundle.bundle_id}'`);
    await run(con, `
    INSERT INTO publications VALUES (
        '${bundle.bundle_id}', '${keyMeta.key_id}', ${bundle.artifact_count}, ${bundle.total_bytes},
        '${receipt.request_token}', '${receipt.publication_id}', '${receipt.status}'
    )
    `);
    console.log(`BUNDLE ${bundle.bundle_id} SIGNED KEY=${keyMeta.key_id}`);
    console.log(`BUNDLE ${bundle.bundle_id} PUBLISHED RECEIPT=${receipt.publication_id} TOKEN=${receipt.request_token} STATUS=${receipt.status}`);
}