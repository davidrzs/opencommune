#!/usr/bin/env bash
# Crawl jobs: document discovery and download only. One process at a time owns
# all download stages, through a lock in DATA_DIR shared with any manual run; workers share the
# per-host and per-network limits. Runs from the repository it lives in, on any machine.
# Usage: deploy/crawl.sh backlog|refresh|fetch
set -euo pipefail
cd "$(dirname "$0")/.."
py=.venv/bin/python
oc=.venv/bin/opencommune
data_dir=$($py -c 'from opencommune.config import settings; print(settings.data_dir.resolve())')
mkdir -p "$data_dir/logs"
exec 9>"$data_dir/download-jobs.lock"
flock -w 14400 9
# Complete the issuer chains some commune sites leave out, anchored in the public roots.
if download_ca=$($py scripts/build_download_ca_bundle.py); then
  export SSL_CERT_FILE="$download_ca"
else
  echo "Issuer bundle unavailable; using the normal TLS roots" >&2
fi
mode=${1:-backlog}
workers=${OPENCOMMUNE_DOWNLOAD_WORKERS:-2}
run_stage() {
  # Do not spend requests when the raw directory is below its configured reserve.
  # The shared download function also checks each PDF and ongoing streams.
  if ! $oc storage-check; then
    echo "Download pass paused for raw archive storage; checkpoints retained" >&2
    exit 0
  fi
  echo "$(date -Is) Starting: $*"
  "$@" || echo "Stage failed ($?): $*; checkpoints retained" >&2
}
case "$mode" in
  backlog)
    # Finite per-commune batches preserve fairness; repeated passes drain inventories.
    run_stage $oc iweb sync --page-budget 12 --limit 50 --max-minutes 45
    run_stage $oc linked-archive fetch --workers "$workers" --limit 100 --max-minutes 60 --commune-max-minutes 2
    run_stage $oc wordpress fetch --workers "$workers" --limit 100 --max-minutes 45 --commune-max-minutes 2
    ;;
  refresh)
    run_stage $oc access-recheck
    # Oldest refresh first; each run advances across the whole configured archive.
    run_stage $oc linked-archive fetch --workers "$workers" --refresh --limit 25 --max-minutes 30 --commune-max-minutes 2
    run_stage $oc wordpress fetch --workers "$workers" --refresh --limit 25 --max-minutes 30 --commune-max-minutes 2
    run_stage $oc iweb sync --refresh --page-budget 12 --limit 25 --max-minutes 30
    ;;
  fetch)
    # The curated sources in data/communes.yaml; known URLs are conditional requests.
    run_stage $oc fetch
    run_stage $oc catalog
    ;;
  *) echo "Expected backlog, refresh or fetch" >&2; exit 2 ;;
esac
echo "$(date -Is) Done: $mode"
