#!/bin/bash
set -euo pipefail
mkdir -p /app/publisher
cp "$(dirname "$0")/release-publisher.mjs" /app/publisher/release-publisher.mjs