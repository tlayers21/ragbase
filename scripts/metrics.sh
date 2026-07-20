#!/bin/bash
# Fetch and display RAGbase metrics from the Pi telemetry server.
# Breaks down latency by query type and shows cache hit rate.

RAW=$(ssh tlayers21@100.80.105.44 "curl -s http://localhost:9000/metrics")

if [ -z "$RAW" ]; then
  echo "No response from telemetry server." >&2
  exit 1
fi

echo "=== RAGbase Metrics ==="
echo ""

echo "--- Raw summary ---"
echo "$RAW" | python3 -m json.tool
echo ""

echo "--- Computed breakdowns ---"
echo "$RAW" | python3 -c "
import json, sys

data = json.load(sys.stdin)
events = data.get('events', data.get('recent', []))

rag_hits   = [e for e in events if e.get('event_type') == 'query_rag' and e.get('metadata', {}).get('cache_hit')]
rag_misses = [e for e in events if e.get('event_type') == 'query_rag' and not e.get('metadata', {}).get('cache_hit')]
direct     = [e for e in events if e.get('event_type') in ('query_direct', 'query') and e.get('metadata', {}).get('mode') == 'direct']

def avg_latency(evs):
    lats = [e['metadata']['latency'] for e in evs if 'latency' in e.get('metadata', {})]
    return f'{sum(lats)/len(lats):.2f}s' if lats else 'n/a'

total_rag = len(rag_hits) + len(rag_misses)
hit_rate  = f'{len(rag_hits)/total_rag*100:.1f}%' if total_rag else 'n/a'

print(f'RAG queries      : {total_rag}')
print(f'  cache hits     : {len(rag_hits)}  ({hit_rate})')
print(f'  cache misses   : {len(rag_misses)}')
print(f'')
print(f'Avg latency (RAG cache hit)  : {avg_latency(rag_hits)}')
print(f'Avg latency (RAG cache miss) : {avg_latency(rag_misses)}')
print(f'Avg latency (direct)         : {avg_latency(direct)}')
print(f'Direct queries   : {len(direct)}')
"
