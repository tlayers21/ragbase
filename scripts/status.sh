#!/bin/bash
# Read-only by design. This used to POST /ingest/clear_completed first, which meant
# a status check destroyed the finished-job rows it was about to print - and, while
# a cancelled job was still running, deleted the record the worker needed to see it
# had been cancelled. Use the UI's "clear finished" button to tidy the queue.

echo "=== Queue Status ==="
curl -s "http://localhost:8001/ingest/status" | python3 -m json.tool

echo ""
echo "=== Recent Log ==="
tail -20 logs/ingestion.pdf.log
