# How to open the admin panel — and why it showed `0 0 0` and hung

Answering the owner's 21:48 question (`how can i see admin panle`), which the Antigravity lane never
answered because that account ran `/logout` at 21:49:47. Every number below was measured on this box
at 22:05 with `curl`, plain HTTP, no restart, and no credential printed.

## What is actually running

One process (`fast_fetch.py serve`) listens on **both** `127.0.0.1:8080` and `127.0.0.1:8081`.
Neither is bound beyond loopback and nginx forwards neither.

| URL | Result | Meaning |
|---|---|---|
| `http://127.0.0.1:8080/` | `200`, 1,355 B | the small public-port landing page, **not** the dashboard |
| `http://127.0.0.1:8080/api/data` | `404`, 40 B | the data feed does not exist on this port |
| `http://127.0.0.1:8081/` | `200`, **46,476 B** | the real dashboard ("Database & Site Explorer"), **no token required** |
| `http://127.0.0.1:8081/api/data` | `200`, **2,533,437 B in 46.6 s** | the payload the dashboard renders |
| `http://127.0.0.1:8081/admin` | `401`, 193 B | the token-gated operator route (`RADD_ADMIN_TOKEN`) |
| `http://92.4.95.252/api/data` | `403` | nginx `^~ /api/` denies it at the public edge |
| `http://92.4.95.252/admin` | `401`, 24 B | falls through to code-server, not our app |
| `http://92.4.95.252/` | `302` | code-server (the web IDE), not the app |

## The two ways to see it

1. **From a terminal on this box:** `curl` is not a UI, so open it in the box's own browser, or use
   method 2.
2. **From your own laptop (the way to actually use it):** keep an SSH tunnel open and browse
   `http://127.0.0.1:8081/` locally.

   ```bash
   ssh -N -L 8081:127.0.0.1:8081 ubuntu@92.4.95.252
   ```

   Then in your browser: `http://127.0.0.1:8081/` for the dashboard, `http://127.0.0.1:8081/admin`
   for the token-gated operator panel. **Do not** try `http://92.4.95.252/admin` — that is the
   code-server login, and it is not our panel.

## Why it showed `0 0 0` and stuck on "loading"

Two distinct causes, and they compound:

- **Opened through the public IP:** `/api/data` is `403` at the edge, so every counter stays at its
  initial `0` and the spinner never finishes. This is the intended boundary, not a bug — the fix is
  the tunnel above, never opening the panel through nginx.
- **Opened on loopback, but the box is busy:** `/api/data` is a **2.5 MB** response that took
  **46.6 s** to produce at 22:05 (load was ~8 on one vCPU with several agent lanes spinning). The
  dashboard renders whatever it has when the fetch resolves, so a slow or interrupted fetch leaves
  `0 0 0` and a permanent loading state. This one *is* a defect and it is tracked as task #10
  ("rebuild the v2 projection and bound `/api/data`"): the payload should be paged and the counts
  should come from the pre-stamped projection, exactly like `/api/v1/stats`, which is 8 ms warm and
  22–42 s cold for the same reason.

Read this file's table again after task #10 lands; if `/api/data` still returns megabytes and tens of
seconds, it is still broken and the dashboard is still unreliable on this hardware.

## What the panel is and is not protected by

The trust boundary on `8081` is **the loopback interface**, not the token: `/` and `/api/data` answer
to anything on this VM without a credential, and `RADD_ADMIN_TOKEN` only guards `/admin`. Never
describe the dashboard as token-gated. The corollary is that any process or lane on this box can read
the whole operator view — which is why `docs/SESSION_CHECKPOINT.md` records q3's
`gate_operator_port`/`_operator_gate` work as the thing that has to land (task #27), and why no
customer PII may be added to that surface until it does.
