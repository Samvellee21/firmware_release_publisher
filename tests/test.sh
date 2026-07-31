#!/bin/bash
# Verifier entrypoint for the firmware-release-publisher task.
#
# Runs the pytest grader (tests/test_outputs.py) against whatever is currently
# installed at /app/publisher/release-publisher.mjs and converts its pass/fail
# into the binary reward file the grading harness reads. Called twice per
# check: once with nothing installed (must write 0) and once after
# solution/publish.sh has run (must write 1).
#
# The distribution-gateway is not started by anything else in this image (no
# CMD runs it, and the documented proof commands don't start it separately
# either), so this script is responsible for bringing it up itself and
# waiting until it actually accepts connections before handing off to pytest.
# Skipping this step means every submission crashes on its first HTTP call to
# the gateway before it ever gets a chance to do real work.
set -u

REPORT_DIR="/logs/verifier"
mkdir -p "$REPORT_DIR"

if [ ! -d /app ]; then
  echo "Error: /app does not exist — this must run inside the task container." >&2
  exit 1
fi

GATEWAY_HOST="127.0.0.1"
GATEWAY_PORT="7070"

port_is_open() {
  (exec 3<>"/dev/tcp/${GATEWAY_HOST}/${GATEWAY_PORT}") >/dev/null 2>&1
  local result=$?
  exec 3>&- 2>/dev/null || true
  return $result
}

if port_is_open; then
  echo "verifier: distribution-gateway already reachable on ${GATEWAY_HOST}:${GATEWAY_PORT}"
else
  echo "verifier: starting distribution-gateway"
  node /app/distribution-gateway/server.js > "$REPORT_DIR/gateway.log" 2>&1 &

  attempt=0
  max_attempts=50   # 50 * 0.2s = up to 10s
  until port_is_open; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "verifier: distribution-gateway never became reachable after ${max_attempts} attempts" >&2
      cat "$REPORT_DIR/gateway.log" >&2 || true
      break
    fi
    sleep 0.2
  done
  echo "verifier: distribution-gateway reachable after ${attempt} check(s)"
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
