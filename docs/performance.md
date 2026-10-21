# Performance

Owner: Do Ngoc Quy. The load-test harness is [`loadtest/run.py`](../loadtest/run.py).

## Local baseline (2026-10-19)

One server process, measured in-process against a simulated ServiceNow that
answers every call after 200 ms. The harness signs in through the full OAuth
flow, then sends `list_incidents` calls at each concurrency level (200 calls
per level). No errors at any level.

| Concurrency | p50 | p95 | p99 | Throughput |
| --- | --- | --- | --- | --- |
| 1 | 447 ms | 451 ms | 454 ms | 2.2 calls/s |
| 10 | 543 ms | 581 ms | 585 ms | 18.6 calls/s |
| 40 | 720 ms | 875 ms | 880 ms | 51.6 calls/s |
| 80 | 1,069 ms | 1,534 ms | 1,536 ms | 65.1 calls/s |
| 160 | 2,439 ms | 2,849 ms | 2,867 ms | 63.3 calls/s |

Sign-in steps: register 2 ms, authorize 1 ms, consent 1 ms, callback 236 ms
(one ServiceNow token exchange), token 2 ms. Claude allows 10 s for each.

Machine: Apple Silicon Mac (arm64), Python 3.14, FastMCP 4.0.5. With no
ServiceNow latency, a call costs about 12 ms of server work and one process
peaks near 85 calls/s.

## Findings

- **Each call makes two ServiceNow round trips.** The broker re-checks the
  user's token against the identity API on every request (so revocation takes
  effect immediately), then calls the Table API. Single-call latency is about
  2 × ServiceNow latency + 45 ms, and ServiceNow sees two requests per tool call.
- **One process saturates near 65 calls/s.** Beyond about 80 concurrent calls,
  more load only adds queueing: p95 passes 1.5 s at 80 and 2.8 s at 160.
  Tools run on a shared pool of 40 worker threads, and server CPU is the limit
  before that pool is.
- **Capacity in user terms:** a Claude conversation turn usually makes one to
  a few tool calls. At 50 calls/s, one process serves roughly 500 people each
  making a call every 10 seconds, with p95 under 1 s. Scaling beyond one
  process needs shared token storage (a large-effort item).
- **Possible optimization (needs security review):** caching a verified token
  for 30–60 s would remove one ServiceNow round trip per call, but a revoked or
  disabled user would keep access for up to that long.

## Limits of this baseline

The client runs in the same process, there is no network or TLS, and
ServiceNow is simulated with a fixed delay. Real numbers depend on the
instance's response times, its rate limits (`429`), and the hosting platform.
Repeat the measurement against staging before go-live and record it here.

## Running the harness

```bash
# Local, simulated ServiceNow (default 200 ms per call)
uv run --locked --extra remote python loadtest/run.py
uv run --locked --extra remote python loadtest/run.py --servicenow-ms 300 --levels 1,20,80 --requests 400

# A deployed server: sign in with any OAuth-capable MCP client, then
MCP_LOADTEST_TOKEN=<mcp access token> uv run --locked --extra remote python loadtest/run.py \
    --url https://mcp.example.com/mcp --levels 1,10 --requests 100
```

Remote mode calls `list_incidents` as the token's user, so every request
reaches ServiceNow. Use a staging instance, keep the levels modest, and get the
service owner's approval first. Each level reports p50/p95/p99 latency,
throughput and errors; `--json` prints a machine-readable report.
