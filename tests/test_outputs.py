import subprocess
import re
import duckdb

MANIFEST_PATH = "/app/fixtures/build_manifest.csv"
DB_PATH = "/app/releases.duckdb"


def run_report():
    result = subprocess.run(
        ["npm", "run", "report", "--silent"],
        cwd="/app",   # the folder containing package.json (hint: /app in the container)
        capture_output=True, text=True, timeout=60,
    )
    return result.stdout


def mask_receipt(text):
    return re.sub(r"RECEIPT=\S+", "RECEIPT=<id>", text)


def expected_bundles():
    """Independently recomputes the publishable bundle set straight from the raw
    manifest fixture, so these tests never trust a number the solution reports —
    they derive the correct answer from the same input the solution was given."""
    con = duckdb.connect(":memory:")
    con.sql(f"CREATE TABLE manifest AS SELECT * FROM read_csv_auto('{MANIFEST_PATH}', header=true)")
    rows = con.sql("""
        SELECT bundle_id, COUNT(*) AS artifact_count, SUM(size_bytes) AS total_bytes
        FROM (SELECT DISTINCT * FROM manifest) b
        WHERE b.record_type = 'BUILD'
          AND NOT EXISTS (
              SELECT 1 FROM (SELECT DISTINCT * FROM manifest) w
              WHERE w.record_type = 'WITHDRAWAL' AND w.supersedes_id = b.entry_id
          )
        GROUP BY bundle_id
        ORDER BY bundle_id
    """).fetchall()
    return {bundle_id: (count, total) for bundle_id, count, total in rows}


def test_report_output_matches_golden():
    actual = run_report()
    expected = open("/app/reports/publications.expected.txt").read()   # path to the golden file
    assert mask_receipt(actual) == mask_receipt(expected)


def test_no_bundle_signed_with_revoked_key():
    actual = run_report()
    assert "UNTRUSTED_SIGNATURE" not in actual   # the error string that must never appear


def test_receipts_persisted_in_duckdb():
    con = duckdb.connect(DB_PATH)
    rows = con.sql("SELECT * FROM publications").fetchall()   # your publications table name
    assert len(rows) == len(expected_bundles())


def test_rerun_is_idempotent():
    first = run_report()
    second = run_report()
    assert first == second


def test_reconciliation_is_correct():
    """Recomputes the correct (bundle_id -> artifact_count, total_bytes) mapping
    from the raw manifest independently of whatever the solution persisted, so a
    hardcoded or faked value in the solution cannot pass this check."""
    expected = expected_bundles()
    con = duckdb.connect(DB_PATH)
    rows = con.sql("SELECT bundle_id, artifact_count, total_bytes FROM publications").fetchall()
    actual = {bundle_id: (count, total) for bundle_id, count, total in rows}
    assert actual == expected


def test_fully_withdrawn_bundle_is_excluded():
    """BND-104 has every one of its builds withdrawn in the fixture; it must
    never surface, not in stdout and not in the persisted table."""
    actual_output = run_report()
    assert "BND-104" not in actual_output
    con = duckdb.connect(DB_PATH)
    rows = con.sql("SELECT bundle_id FROM publications WHERE bundle_id = 'BND-104'").fetchall()
    assert rows == []
