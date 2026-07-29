#!/bin/bash
# Verifier entrypoint for the firmware-release-publisher task.
#
# Runs the pytest grader (tests/test_outputs.py) against whatever is currently
# installed at /app/publisher/release-publisher.mjs and converts its pass/fail
# into the binary reward file the grading harness reads. Called twice per
# check: once with nothing installed (must write 0) and once after
# solution/publish.sh has run (must write 1).
set -u

REPORT_DIR="/logs/verifier"
mkdir -p "$REPORT_DIR"

if [ ! -d /app ]; then
  echo "Error: /app does not exist — this must run inside the task container." >&2
  exit 1
fi

python3 -m pytest --ctrf "$REPORT_DIR/ctrf.json" /tests/test_outputs.py -rA
pytest_exit_code=$?
echo "verifier: pytest exited with code ${pytest_exit_code}"

if [ "$pytest_exit_code" -eq 0 ]; then
  reward=1
else
  reward=0
fi

echo "$reward" > "$REPORT_DIR/reward.txt"
echo "verifier: wrote reward=${reward} to ${REPORT_DIR}/reward.txt"
