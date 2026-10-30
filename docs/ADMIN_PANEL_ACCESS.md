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
| `http://127.0.0.1:8081/admin` | `401`, 193 B | the only route on that port that consulted `RADD_ADMIN_TOKEN` |
| `http://92.4.95.252/api/data` | `403` | nginx `^~ /api/` denies it at the public edge |
| `http://92.4.95.252/admin` | `401`, 24 B | falls through to code-server, not our app |
| `http://92.4.95.252/` | `302` | code-server (the web IDE), not the app |

**Read that table as the state of the *running tree*, not of the repository.** Both rows above that
say "no token" and "2,533,437 B" are true of `/opt/radd-stream` today: the unit's `ExecStart` loads
that checkout, and it is far behind trunk. In the code, `admin_panel.gate_operator_port` requires the
bearer token on **every** route of `8081` (fail-closed when `RADD_ADMIN_TOKEN` is unset) and
`viewer.fetch_database_payload` serves one bounded page of the ledger instead of the whole table.
Neither is deployed, so neither is what `curl` answers on this box until the owner lands and restarts.
Do not quote the last column as fixed, and do not quote it as broken — quote which tree you measured.

## The two ways to see it

1. **From a terminal on this box:** `curl` is not a UI, so open it in the box's own browser, or use
   method 2.
2. **From your own laptop (the way to actually use it):** keep an SSH tunnel open and browse
   `http://127.0.0.1:8081/` locally.

   ```bash
   ssh -N -L 8081:127.0.0.1:8081 ubuntu@92.4.95.252
   ```

   Prerequisites, measured on this box rather than assumed: `AllowTcpForwarding` is **not set** in
   `/etc/ssh/sshd_config` or in `sshd_config.d/` (the only drop-in,
   `60-cloudimg-settings.conf`, sets `PasswordAuthentication no`), so it is at OpenSSH's default of
   `yes` and the forward is permitted. But key authentication is the **only** method — the owner must
   connect with the same private key the box was provisioned with; a password will not work. And
   `ss -Hltnp` confirms both ports are bound to `127.0.0.1` only, from one `python3` process
   (pid 1361081, fds 9 and 10), which is why the tunnel is required at all.

   Then in your browser: `http://127.0.0.1:8081/` for the dashboard, `http://127.0.0.1:8081/admin`
   for the operator panel (loopback-only, and it asks for `RADD_ADMIN_TOKEN`). **Do not** try
   `http://92.4.95.252/admin` — that is the
   code-server login, and it is not our panel.

## Why it showed `0 0 0` and stuck on "loading"

Two distinct causes, and they compound:

- **Opened through the public IP:** `/api/data` is `403` at the edge, so every counter stays at its
  initial `0` and the spinner never finishes. This is the intended boundary, not a bug — the fix is
  the tunnel above, never opening the panel through nginx.
- **Opened on loopback, but the box is busy:** `/api/data` was a **2.5 MB** response that took
  **46.6 s** to produce at 22:05 (load was ~8 on one vCPU with several agent lanes spinning). The
  dashboard renders whatever it has when the fetch resolves, so a slow or interrupted fetch leaves
  `0 0 0` and a permanent loading state. This one *was* the defect tracked as task #10
  ("rebuild the v2 projection and bound `/api/data`"), and it is **closed in code, not in
  deployment**: `fetch_database_payload` now returns one page (`_LEDGER_PAGE_DEFAULT` 50,
  `_LEDGER_PAGE_CEILING` 200, clamped rather than refused) with `page.truncated`, `page.clamped`
  and `page.ceiling` on the wire, and `stats` defaults to the pre-stamped projection instead of a
  live scan. Pinned by `Fast_Fetch/test_bounded_ledger.py` and
  `Fast_Fetch/test_operator_read_bounds.py`. No fresh production number is quoted here: reading
  `/api/data` against the live catalog is forbidden to agent lanes, so the megabyte figure above
  stays the only measured one and it belongs to the unbounded reader.

What the last two rows of the table describe is therefore *this box*, not *this repository* — if you
land the bounded page and restart, re-measure `curl -w` on `127.0.0.1:8081/api/data?limit=200` and
write the number here instead of guessing at it.

## What the panel is and is not protected by

The trust boundary on `8081` is **the loopback interface** — nginx forwards neither port, and this
whole surface is unreachable from outside the VM. Never describe the dashboard as token-gated:
holding `RADD_ADMIN_TOKEN` does not make it reachable, and describing it that way is how a reader
concludes a password is the reason nobody else can see it.

The token is the *second* thing, and it is checked after loopback inside `admin_panel._gate`, on
every route of that port, fail-closed when the variable is unset. That ordering is the whole design:
reachability is the interface, the credential is the door on the port that already cannot be reached.

On the running tree the second check is not in force, because `/opt/radd-stream` is behind trunk and
`ExecStart` loads that checkout: `/` and `/api/data` still answer anything on this VM without a
credential, and `RADD_ADMIN_TOKEN` still guards only `/admin` there. The corollary holds until it is
deployed — any process or lane on this box can read the whole operator view — which is why no
customer PII may be added to that surface before the gate is live, and why landing it is not the same
act as deploying it.
