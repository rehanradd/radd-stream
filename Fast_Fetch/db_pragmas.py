"""Serve-path SQLite pragmas, in one place (Session 125 scale quick wins).

Every connection the HTTP service opens — catalog or user-state, read-write
or read-only — goes through :func:`apply_serve_pragmas`. Pragmas are
per-connection in SQLite (except ``journal_mode``), so a helper nobody calls
is the same as no helper at all; the call sites are:

* ``fast_fetch.get_db`` (catalog; scrapers, CLI and maintenance share it),
* ``viewer.get_db`` (catalog; one connection per v1 request),
* ``api_v2.session`` (catalog; one connection per v2 request),
* ``admin_panel._session`` (catalog; remote-config reads in-process),
* ``accounts.connect`` / ``engagement.connect`` (user-state DB) and
  ``accounts._open_catalog_read_only`` (visibility oracle),
* ``redact._connect`` (art / stream redirector lookups),
* ``panel_feed._open_panel`` (panel DB, read-only).

NOT covered, deliberately: projection / evidence / merge / importer /
backfill / audit helpers (``catalog_v2.project_db``,
``fast_fetch.reconcile_key_adult``, the ``import_*`` staging writers).
Those are CLI tools on their own files, not request paths, and their
connections are short-lived bulk writes — the serve values would not help
them and changing them is churn without a reader.

Values (Session 125):

* ``cache_size = -65536`` — 64 MiB of page cache *per connection*. The
  server is ``ThreadingMixIn``: one thread per TCP connection, unbounded by
  design, so the per-connection cap is the only bound that exists. The
  practical concurrency is the nginx edge: ``limit_conn 32`` per IP and the
  10 r/s browse bucket, requests ~0.15 s, so even 32 IPs hammering at once
  is ~64 in-flight connections. 64 x 64 MiB = 4 GiB worst-case cap, and
  the cap is not a preallocation — SQLite only allocates pages it touches,
  so the usual tens of connections hold well under 1 GiB. The note's
  -131072 (128 MiB) would double the worst case to 8 GiB on a 12 GiB
  box, too close to the MemAvailable < 1500 MB guardrail.
* ``mmap_size = 268435456`` — 256 MiB of address space, not RAM: the OS
  only pages in what is touched. It does not help the WAL file, which is
  why the checkpoint stays at 1000 pages.
* ``temp_store = MEMORY`` — sorts and temp tables out of the disk.
* ``busy_timeout`` stays **30000** on catalog connections (the live value
  since the service started; the build note's 5000 would *lower* it).
  The user-state helpers keep their own existing 5000 ms default.
* WAL + ``synchronous = NORMAL`` + ``wal_autocheckpoint = 1000``,
  unchanged from the live setup.

Stdlib only (``sqlite3``); this module imports nothing from the project,
so no import cycle is possible no matter who calls it.
"""

import sqlite3

#: Page cache per connection, in KiB when negative: -65536 = 64 MiB.
CACHE_SIZE_PAGES = -65536

#: Memory-map window per connection, in bytes: 256 MiB of address space.
MMAP_SIZE_BYTES = 268435456

#: Temp tables and sorts live in RAM, not on the disk.
TEMP_STORE = "MEMORY"

#: Lock-wait on catalog connections, in ms — the live value, kept.
BUSY_TIMEOUT_MS = 30000

#: Durability for WAL mode: a commit may sit in the OS page cache.
SYNCHRONOUS = "NORMAL"

#: WAL checkpoint after this many pages (~4 MiB at the 4 KiB page size).
WAL_AUTOCHECKPOINT_PAGES = 1000


def apply_serve_pragmas(conn: sqlite3.Connection, *,
                        busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> None:
    """Apply the serve-path pragmas to an already-open connection.

    Safe on read-only handles: ``journal_mode`` is the one pragma that
    needs write access, so it is guarded — on a ``mode=ro`` connection it
    simply reports the file's current mode. Everything else here is
    per-connection state and applies read or write.
    """
    conn.execute("PRAGMA busy_timeout = %d" % int(busy_timeout_ms))
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass  # read-only handle: the file's journal mode is not ours to set
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA cache_size = %d" % CACHE_SIZE_PAGES)
    conn.execute("PRAGMA mmap_size = %d" % MMAP_SIZE_BYTES)
    conn.execute("PRAGMA temp_store = %s" % TEMP_STORE)
    conn.execute("PRAGMA synchronous = %s" % SYNCHRONOUS)
    conn.execute("PRAGMA wal_autocheckpoint = %d" % WAL_AUTOCHECKPOINT_PAGES)


def read_pragmas(conn: sqlite3.Connection) -> dict:
    """The serve values back off a live connection, for tests and probes."""
    names = ("journal_mode", "busy_timeout", "foreign_keys", "cache_size",
             "mmap_size", "temp_store", "synchronous", "wal_autocheckpoint")
    out = {}
    for name in names:
        # `mmap_size` answers no row on a :memory: database (there is
        # nothing to map); every other pragma answers one row.
        row = conn.execute("PRAGMA %s" % name).fetchone()
        out[name] = row[0] if row is not None else None
    return out
