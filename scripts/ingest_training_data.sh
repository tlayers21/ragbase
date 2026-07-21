#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data/training_data"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8001}"

slugify() {
  local input="$1"
  echo "$input" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//'
}

ingest_one() {
  local file_path="$1"
  local base_name
  local source

  base_name="$(basename "${file_path}" .pdf)"
  source="$(slugify "${base_name}")"

  echo "Ingesting: ${base_name} -> source='${source}'"
  curl -sS -X POST "${API_BASE_URL}/ingest/file" \
    -F "file=@${file_path}" \
    -F "source=${source}" >/dev/null
}

main() {
  if [[ ! -d "${DATA_DIR}" ]]; then
    echo "Training data directory not found: ${DATA_DIR}" >&2
    exit 1
  fi

  local files=("${DATA_DIR}"/*.pdf)
  if [[ ! -e "${files[0]}" ]]; then
    echo "No PDF files found in ${DATA_DIR}" >&2
    exit 1
  fi

  echo "Queueing ${#files[@]} files via ${API_BASE_URL}"
  for file_path in "${files[@]}"; do
    ingest_one "${file_path}"
  done

  echo "Done queueing files."
  echo "Check queue status: curl -sS ${API_BASE_URL}/ingest/status"
}

main "$@"
