import subprocess
import re
import duckdb

def run_report():
    result = subprocess.run(
        ["npm", "run", "report","--silent"],
        cwd="/app",   # the folder containing package.json (hint: /app in the container)
        capture_output=True, text=True, timeout=60,
    )
    return result.stdout

def mask_receipt(text):
    return re.sub(r"RECEIPT=\S+", "RECEIPT=<id>", text)

def test_report_output_matches_golden():
    actual = run_report()
    expected = open("/app/reports/publications.expected.txt").read()   # path to the golden file
    assert mask_receipt(actual) == mask_receipt(expected)

def test_no_bundle_signed_with_revoked_key():
    actual = run_report()
    assert "UNTRUSTED_SIGNATURE" not in actual   # the error string that must never appear

def test_receipts_persisted_in_duckdb():
    con = duckdb.connect("/app/releases.duckdb")   # path to releases.duckdb, relative to cwd above
    rows = con.sql("SELECT * FROM publications").fetchall()   # your publications table name
    assert len(rows) == 3

def test_rerun_is_idempotent():
    first = run_report()
    second = run_report()
    assert first == second


def test_reconciliation_is_correct():
    con = duckdb.connect("/app/releases.duckdb")
    row = con.sql("SELECT artifact_count, total_bytes FROM publications WHERE bundle_id = 'BND-101'").fetchone()
    assert row == (9, 1201575)