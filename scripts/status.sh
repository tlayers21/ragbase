#!/bin/bash
# Clear completed jobs first
curl -s -X POST "http://localhost:8001/ingest/clear_completed" > /dev/null

echo "=== Queue Status ==="
curl -s "http://localhost:8001/ingest/status" | python3 -m json.tool

echo ""
echo "=== Recent Log ==="
tail -20 logs/ingestion.pdf.log
