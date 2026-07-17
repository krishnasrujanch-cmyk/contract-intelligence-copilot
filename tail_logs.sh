#!/bin/bash
# Tail Google Cloud Run logs for contract-intelligence-copilot
# Usage: bash tail_logs.sh

PROJECT=${1:-contractintelliegenceplatform}
SERVICE=${2:-contract-intelligence-copilot}
REGION=${3:-us-central1}

echo "Tailing logs for $SERVICE in $PROJECT ($REGION)"
echo "Press Ctrl+C to stop"
echo "================================================"

while true; do
  gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE" \
    --project $PROJECT \
    --limit 5 \
    --freshness 1m \
    --format "value(textPayload)" 2>/dev/null | grep -v "^$"
  echo "--- $(date) ---"
  sleep 3
done
