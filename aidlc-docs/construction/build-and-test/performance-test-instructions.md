# Performance Test Instructions — Content Library Rework

## Performance Requirements

| Metric | Target | Source |
|---|---|---|
| `GET /library` search p95 | ≤ 1 000 ms | NFR-CL-PERF-1 |
| `GET /library/tags` autocomplete p95 | ≤ 200 ms | O(1) GetItem — should be fast |
| `POST /library` add resource p95 | ≤ 500 ms | Single PutItem + optional S3 presign |

---

## Key Performance Characteristics to Validate

### Search (`GET /library`)

The query traverses GSI1 with an in-memory predicate. At 10,000+ items the predicate
filters in Lambda after the index returns matching rows. Performance depends on:

1. **Hit rate** — if the keyword is selective, few rows return from DynamoDB, predicate
   cost is negligible.
2. **Miss rate** — if the keyword matches many rows but filters remove most (e.g., format
   filter eliminates 90%), Lambda will fetch multiple pages before filling the requested
   limit. This is the critical path to validate.

**Test scenario — selective keyword (expected fast)**:
```
GET /library?q=<rare-word>&limit=10
Target: p95 < 300ms
```

**Test scenario — broad keyword with format filter (stress case)**:
```
GET /library?q=aws&format=Slides&limit=10
Target: p95 < 1000ms with 10,000 items in Library
```

### Tags Autocomplete (`GET /library/tags`)

One `GetItem` on the `TAGS#ALL` singleton. At any Library size this is a
single-row read — cost is constant. Should be well under 100ms at p99.

```
GET /library/tags?prefix=ser
Target: p95 < 100ms
```

---

## Load Test Approach

The platform uses AWS Lambda + DynamoDB on-demand. No pre-provisioning is needed
for expected community-scale traffic. Performance tests can be executed
after deployment to dev using a simple script:

```bash
# Install httpx for async requests
pip install httpx

# Simple load test: 50 concurrent search requests
python3 << 'EOF'
import asyncio, httpx, time, statistics

TOKEN = "<your-cognito-token>"
URL = "https://<api-id>.execute-api.us-east-1.amazonaws.com/dev/library"
PARAMS = {"q": "serverless", "limit": "10"}
N = 50

async def one_request(client):
    t0 = time.monotonic()
    r = await client.get(URL, params=PARAMS, headers={"Authorization": f"Bearer {TOKEN}"})
    return (time.monotonic() - t0) * 1000, r.status_code

async def run():
    async with httpx.AsyncClient(timeout=10) as client:
        results = await asyncio.gather(*[one_request(client) for _ in range(N)])
    latencies = [r[0] for r in results]
    codes = [r[1] for r in results]
    p95 = sorted(latencies)[int(0.95 * N)]
    print(f"N={N}, p50={statistics.median(latencies):.0f}ms, p95={p95:.0f}ms, 200s={codes.count(200)}")

asyncio.run(run())
EOF
```

**Expected output**: p95 < 1000ms, all 200s for a Library with representative data.

---

## Notes

- **DynamoDB on-demand** scales automatically; no capacity planning needed for community scale.
- **Lambda cold start** is the dominant latency contributor at low traffic — warm container
  p95 will be significantly faster than cold-start p95.
- **TAGS#ALL singleton contention**: at high concurrent write rates (unlikely for a community
  platform) the ADD operation on the string set could be a hot key. At expected volumes
  (tens of writes per hour) this is not a concern.
- **Full performance testing** (k6, JMeter) is deferred to production readiness review —
  community-scale traffic does not warrant dedicated load infrastructure.
