#!/usr/bin/env python3
"""
Fast_Fetch/payments.py — the JazzCash / EasyPaisa / Raast ledger and the VIP
entitlement it buys. Stdlib only.
════════════════════════════════════════════════════════════════════════════════════
WHAT THIS IS (docs/FULL_MASTER_FEATURE_INVENTORY.md §M-MON-01)
--------------------------------------------------------------------------------
A user can pay; until this module nothing could ever *become* VIP. The flow is
deliberately manual, because the host has no payment gateway and no TLS:

  1. the app shows the operator's payment handles (`/api/v1/app/remote-config`,
     built by `admin_panel.remote_config`) and the user sends PKR out-of-band;
  2. the user posts the transaction id here — `submit_payment()` — which stores
     it as `pending` against a price the SERVER chose, never one the client sent;
  3. the operator reads the SMS on their own phone, and approves or rejects on
     `/admin/payments` (`admin_panel`, loopback only);
  4. approval is what writes `user_accounts.vip_until`. Nothing else does.

There is no webhook to trust and no bank session to verify, so the ledger records
a *claim* until a human confirms it. `status` is the whole difference between the
two, and `pending` is never an entitlement.

WHAT THIS IS NOT
--------------------------------------------------------------------------------
* **Not a payment processor.** No money moves here, no card data, no gateway
  credential, no 3-D Secure. A TID pasted into this endpoint proves nothing except
  that somebody typed it — which is why the default answer is `pending` and a
  human is the only path to VIP.
* **Not self-service pricing.** The plan name is the only price input a caller
  gets. A body carrying `amount_pkr`/`amount` is refused: an endpoint that priced
  the request would let anyone buy a year for PKR 1, or worse, let a bug in a
  client sell VIP for nothing.
* **Not an anonymous ledger.** Every row is bound to an account id. The account
  surface never sees it back; the operator surface sees a one-way fingerprint of
  the account's stored key hash (`account_hint`) so a paying human can be matched
  to a row without the row being enumerable or the hash being printable.

SECRETS AND PROVENANCE (absolute)
--------------------------------------------------------------------------------
* A transaction id is a payment artifact. It is stored, it is shown on the
  loopback operator screen (that is the entire point of the screen), and it
  appears in NO response of the account surface and in NO log line.
* A sync key, its hash, and its full hash never leave this module. `account_hint`
  is a truncated, salted, second-generation digest — a display label, not a
  credential, and useless for recovering anything.
* Every public body this feeds is projected key-by-key (`accounts_api` +
  `redact.VIEWS`), never `dict(row)` and never `SELECT *`.
* An 18+ work is a catalog rule (`API_V2.md` §13) and a payment carries no work at
  all, so there is nothing here to suppress; nothing here may be reached without
  either a bearer sync key or the loopback operator gate.

THE ONE TRANSACTION
--------------------------------------------------------------------------------
`approve_payment()` reads the payment, reads `vip_until`, extends it, marks the
payment reviewed and writes the audit row inside a single `BEGIN IMMEDIATE`
transaction, and its final `UPDATE ... WHERE status = 'pending'` is guarded by
`rowcount`. Two operators clicking the same row, or one operator clicking twice
because the page was slow, therefore cannot credit the same payment twice: the
second call loses the row-lock or finds a non-`pending` status and returns
`changed: False` having written nothing. The extension is
`max(now, vip_until) + days(plan)` so an early renewal is banked rather than
restarted.

Stdlib only: `sqlite3`, `hashlib`, `hmac`, `re`, `time`, `os`, `urllib.request`.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

import accounts

# ── the plan table (the ONLY thing that decides a price) ─────────────────────
#: plan -> (default PKR, VIP days). Days, not months: `vip_until` is epoch
#: seconds and a 30-day month is what a renewal arithmetic can actually do.
#: PKR 250/month and PKR 1,500/year are `MONETIZATION_AND_FLEET_PLAN.md`'s own
#: numbers (line 46: "Monthly VIP: ₨ 250"); the owner ruled on 2026-10-29 that
#: that plan is authoritative, so the earlier 200 in `PAKISTAN_OPERATOR_GUIDE.md`
#: is a defect, not a second opinion. The yearly default is the guide's, the
#: monthly default is the operator's editable one
#: (`app_remote_config.vip_monthly_pkr`), and a saved price wins over these
#: figures whenever that row can be read. This is the never-configured fallback.
PLAN_DEFAULTS = {
    "vip_monthly": (250, 30),
    "vip_yearly": (1500, 365),
}

#: The settings row `admin_panel` owns. Read here by column name rather than by
#: importing that module: `admin_panel` imports THIS one, and a cycle would be an
#: import-time crash, not a style problem.
_PRICE_TABLE = "app_remote_config"
_PRICE_ID = 1
_PRICE_COLUMNS = {"vip_monthly_pkr": "vip_monthly", "vip_yearly_pkr": "vip_yearly"}
_MAX_PKR = 10_000_000

#: The methods the guide names. `nayapay`/`till_id` have no TID shape to check, so
#: they are deliberately absent until someone documents one — an unvalidated
#: method is a column full of prose.
METHODS = ("jazzcash", "easypaisa", "raast")

#: A TID, per method, as the confirmation SMS actually writes it.
#: `PAKISTAN_OPERATOR_GUIDE.md` documents the JazzCash 10-digit TID (e.g.
#: 9823145671). EasyPaisa writes a longer numeric reference and Raast an opaque
#: alphanumeric one; both bounds are the honest envelope of what those SMS bodies
#: contain, and both are stated here rather than guessed at in a client. A shape
#: too loose stores garbage a human cannot read; a shape too tight refuses a real
#: payment, which loses money for the operator and VIP for the payer.
TID_SHAPES = {
    "jazzcash": re.compile(r"[0-9]{10}"),
    "easypaisa": re.compile(r"[0-9]{10,14}"),
    "raast": re.compile(r"[A-Za-z0-9]{12,28}"),
}
#: A TID is never printed into a log or a response; keeping the cap small keeps
#: that promise cheap.
MAX_TID_CHARS = 40

#: One submission per account per window. Without it, a paid-but-typing user can
#: fill the operator's queue with duplicate claims for one SMS, and anyone with a
#: key can do it on purpose.
PAYMENT_MIN_INTERVAL_SECONDS = 300.0
#: Rows one operator page reads. The queue is small by construction; a cap is for
#: the day it is not.
MAX_LEDGER_ROWS = 200

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)

#: The exact columns this module reads. An explicit list, so no column a later
#: release adds can ride out to a client by accident.
_PAYMENT_COLUMNS = ("id", "account_id", "plan", "amount_pkr", "method", "tid",
                    "status", "submitted_at", "reviewed_at", "reviewer_note")

#: An audit row names no TID and no key: `payment_id` is the pointer back to the
#: ledger for whoever has to explain a credit two years from now.
_AUDIT_COLUMNS = ("payment_id", "account_id", "action", "prior_vip_until",
                  "new_vip_until", "reviewer", "note", "acted_at")

_HINT_SALT = "radd-payment-hint:v1:"
_HINT_CHARS = 8


# ── errors: the same vocabulary the account edge already maps ────────────────

class PaymentError(accounts.AccountError):
    """Base for a ledger refusal. Inherits the `code`/`status`/`detail` shape
    `accounts_api._refused` already knows how to turn into a §16.4 problem body,
    so a payment refusal is shaped exactly like an account refusal and invents no
    public code."""

    code = "invalid_params"
    status = 400
    default_detail = "that payment could not be recorded"


class InvalidPayment(PaymentError):
    """Unknown plan, unknown method, a TID that is not a TID, or a client that
    tried to set its own price. Same answer for all of them, and it names no
    field content."""

    code = "invalid_params"
    status = 400
    default_detail = "that payment could not be recorded"


class PaymentRateLimited(accounts.Locked):
    """This account already submitted a payment inside the window. `retry_after`
    is the §16.5 `Retry-After` the caller must send."""

    code = "rate_limited"
    status = 429
    default_detail = "a payment was already submitted for this account"


class PaymentNotFound(PaymentError):
    """No such ledger row — the identical answer for an id that never existed and
    one another operator already closed, because an operator surface is still not
    an oracle for what this server has seen."""

    code = "not_found"
    status = 404
    default_detail = "not found"


# ── plans and prices ─────────────────────────────────────────────────────────

def plan_names() -> tuple:
    """The plans on offer, in the order the app should print them."""
    return tuple(PLAN_DEFAULTS)


def plan_days(plan) -> int:
    """VIP days one plan buys, `0` for a plan we do not sell. A `0` here makes an
    approval a no-op rather than a crash, so callers must check it."""
    entry = PLAN_DEFAULTS.get(str(plan or ""))
    return int(entry[1]) if entry else 0


def default_price(plan) -> int:
    entry = PLAN_DEFAULTS.get(str(plan or ""))
    return int(entry[0]) if entry else 0


def _pkr(value):
    """A stored price as an int, or ``None`` when it is not usable as one.
    ``bool`` is excluded on purpose: SQLite has no boolean, and a column holding
    ``1`` where a price should be is a mistake, not PKR 1."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > _MAX_PKR:
        return None
    return number


def price_table(catalog_path=None) -> dict:
    """`plan -> PKR`, the operator's saved prices where they can be read and the
    module defaults everywhere else.

    Read-only and best-effort: a deployment with no settings row, no catalog file,
    or a catalog this process cannot open still sells the documented plans at the
    documented prices. Falling back is not a failure mode here — a price the
    operator never saved is not a reason to refuse a paying user — but a price
    read from the row is authoritative the moment it is valid, so a client can
    never choose its own."""
    prices = {plan: default for plan, (default, _days) in PLAN_DEFAULTS.items()}
    if not catalog_path:
        return prices
    path = Path(str(catalog_path))
    if not path.exists():
        return prices
    uri = "file:%s?mode=ro" % urllib.request.pathname2url(str(path))
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(%s)" % _PRICE_TABLE)}
            wanted = [column for column in _PRICE_COLUMNS if column in columns]
            if not wanted:
                return prices
            row = conn.execute(
                "SELECT %s FROM %s WHERE id = ?"
                % (", ".join(wanted), _PRICE_TABLE), (_PRICE_ID,)).fetchone()
            if row is None:
                return prices
            for index, column in enumerate(wanted):
                number = _pkr(row[index])
                if number is not None:
                    prices[_PRICE_COLUMNS[column]] = number
        finally:
            conn.close()
    except sqlite3.Error:
        return prices
    return prices


def price_for(plan, catalog_path=None) -> int:
    """What one plan costs right now, or ``0`` for a plan we do not sell."""
    if str(plan or "") not in PLAN_DEFAULTS:
        return 0
    return price_table(catalog_path)[str(plan)]


# ── the ledger ───────────────────────────────────────────────────────────────

def account_hint(key_hash) -> str:
    """A display label for an account, from its stored key hash.

    One-way twice over: the stored value is already ``sha256:``, and this is a
    salted digest of THAT, truncated to 8 hex characters. It lets the operator
    match "the account that says it paid" to a row without putting a hash, a key
    or anything reversible in a body. Accounts with no payments produce nothing,
    and a hint cannot be searched backwards for an account."""
    text = str(key_hash or "")
    if not text:
        return ""
    return "acct-" + hashlib.sha256((_HINT_SALT + text).encode("utf-8")).hexdigest()[:_HINT_CHARS]


def _clean_tid(method, tid) -> str:
    """The transaction id, or a refusal.

    A TID is compared against the method's shape with no whitespace, no control
    characters and no surrounding prose — the SMS reference is a token, and the
    operator reads hundreds of them a day. `tid` is only ever the user's own
    claim; nothing here verifies it against anything."""
    text = str(tid if tid is not None else "").strip()
    if not text or len(text) > MAX_TID_CHARS:
        raise InvalidPayment()
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise InvalidPayment()
    shape = TID_SHAPES.get(str(method or ""))
    if shape is None or not shape.fullmatch(text):
        raise InvalidPayment()
    return text


def _clean_plan(plan) -> str:
    name = str(plan or "").strip().lower()
    if name not in PLAN_DEFAULTS:
        raise InvalidPayment("unknown plan")
    return name


def _clean_method(method) -> str:
    name = str(method or "").strip().lower()
    if name not in TID_SHAPES:
        raise InvalidPayment("unknown method")
    return name


def _clean_reviewer(reviewer) -> str:
    """A free-text operator label for the audit row: printable ASCII, short, no
    markup. It names a person to a human reader and nothing to a machine."""
    text = re.sub(r"[^\x20-\x7e]", "", str(reviewer or ""))[:40].strip()
    return text or "operator"


def _clean_note(note) -> str:
    text = re.sub(r"[^\x20-\x7e]", "", str(note or ""))[:200].strip()
    return text


def _recent_gap(conn, account_id, now: float) -> float:
    """Seconds since this account's last submission, or a huge number if there
    is none. Uses the (account_id, submitted_at) index; the window question is
    asked on every submit and must not table-scan the ledger."""
    row = conn.execute(
        "SELECT submitted_at FROM payment_transactions WHERE account_id = ?"
        " ORDER BY submitted_at DESC LIMIT 1", (int(account_id),)).fetchone()
    if row is None:
        return float("inf")
    return now - float(row["submitted_at"] or 0)


def submit_payment(conn_or_path, account_id, *, plan, method, tid,
                   catalog_path=None, now: float | None = None,
                   min_interval: float = PAYMENT_MIN_INTERVAL_SECONDS) -> dict:
    """File one claimed payment as `pending`. Returns `{"payment_id", "status",
    "plan", "amount_pkr", "method", "submitted_at"}`.

    The amount is looked up, never accepted: `amount_pkr` in this response is what
    THIS server charges for that plan at that moment (the operator's saved price
    when it can be read), which is also what the operator will check their SMS
    against. A client that sent its own amount got a 400 before reaching here (see
    `accounts_api`).

    Raises `InvalidPayment` (400) for an unknown plan/method or a bad TID shape
    and `PaymentRateLimited` (429, `Retry-After`) for a second submission inside
    the window. The rate limit is checked inside the same transaction as the
    insert, so two parallel POSTs from one account cannot both land."""
    name = _clean_plan(plan)
    way = _clean_method(method)
    reference = _clean_tid(way, tid)
    amount = _pkr(price_table(catalog_path).get(name))
    if amount is None or amount <= 0:
        # A zero price is not "free VIP", it is a broken settings row.
        raise PaymentError("the price of that plan is unavailable")
    moment = time.time() if now is None else float(now)
    with accounts._borrow(conn_or_path) as conn:
        owns = _begin_immediate(conn)
        try:
            gap = _recent_gap(conn, account_id, moment)
            if gap < float(min_interval):
                if owns:
                    conn.rollback()
                raise PaymentRateLimited(retry_after=float(min_interval) - gap)
            conn.execute(
                "INSERT INTO payment_transactions(account_id, plan, amount_pkr,"
                " method, tid, status, submitted_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?)",
                (int(account_id), name, amount, way, reference,
                 STATUS_PENDING, moment))
            payment_id = int(conn.execute(
                "SELECT last_insert_rowid()").fetchone()[0])
            if owns:
                conn.commit()
        except accounts.Locked:
            raise
        except sqlite3.Error as error:
            if owns:
                _rollback(conn)
            raise _ledger_unavailable() from error
    return {"payment_id": payment_id, "status": STATUS_PENDING, "plan": name,
            "amount_pkr": amount, "method": way, "submitted_at": moment}


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except sqlite3.Error:
        pass


def _ledger_unavailable() -> PaymentError:
    """The one answer for a failed ledger write. The exception is never
    interpolated: SQLite text can carry the database file path, and a path is not
    something a public 500 detail gets to say."""
    return PaymentError("the payment ledger is unavailable")


def _begin_immediate(conn) -> bool:
    """Start a write transaction if the caller is not already inside one.

    `BEGIN IMMEDIATE` takes the write lock at the START of the transaction, so
    two operators approving one payment serialize instead of both reading
    `pending` and both writing. Legacy isolation auto-begins on the first DML, so
    a caller that already inserted something must not be handed a nested BEGIN —
    that is an error, not a no-op. Returns True when THIS call opened the
    transaction and therefore owns the commit."""
    if conn.in_transaction:
        return False
    conn.execute("BEGIN IMMEDIATE")
    return True


def _payment_row(conn, payment_id) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT %s FROM payment_transactions WHERE id = ?"
        % ", ".join(_PAYMENT_COLUMNS), (int(payment_id),)).fetchone()


def _review(conn_or_path, payment_id, *, action, reviewer, note, now,
            credit_days: int | None) -> dict:
    """The one close-out path for both actions.

    Reads the row, decides, writes and audits inside a single IMMEDIATE
    transaction. `credit_days` is None for a reject, which is exactly how the
    reject path guarantees it cannot touch `vip_until`: the UPDATE that would
    write it is never constructed.

    Idempotency: the final UPDATE carries `AND status = 'pending'` and the result
    is judged by `rowcount`, so a replay of this call finds a closed row and
    returns `changed: False` having written nothing at all — no second credit, no
    second audit row for a credit that did not happen."""
    moment = time.time() if now is None else float(now)
    who = _clean_reviewer(reviewer)
    why = _clean_note(note)
    with accounts._borrow(conn_or_path) as conn:
        owns = _begin_immediate(conn)
        try:
            row = _payment_row(conn, payment_id)
            if row is None:
                raise PaymentNotFound()
            status = str(row["status"] or "")
            if status not in _STATUSES:
                # A ledger row that says something else is data damage, and a
                # credit built on it would be a guess.
                raise PaymentNotFound()
            account = conn.execute(
                "SELECT vip_until, revoked_at FROM user_accounts WHERE id = ?",
                (int(row["account_id"]),)).fetchone()
            stored = float(account["vip_until"] or 0) if account else 0.0
            if status != STATUS_PENDING:
                # Already closed: the honest idempotent answer, and the reason a
                # double-click and a network retry are the same event. Nothing is
                # written, so nothing can be double-credited.
                if owns:
                    _rollback(conn)
                return {"payment_id": int(row["id"]), "status": status,
                        "changed": False, "account_id": int(row["account_id"]),
                        "vip_until": stored, "prior_vip_until": stored,
                        "days": 0,
                        "reviewed_at": float(row["reviewed_at"] or 0)}
            prior = stored
            new = stored
            days = 0
            if credit_days is not None:
                days = int(credit_days)
                if account is None or account["revoked_at"] is not None:
                    # The payer's account is gone or revoked. Approving into a row
                    # nobody can read would tell the operator a credit happened;
                    # refuse loudly instead of writing a lie into the audit.
                    raise PaymentNotFound()
                # max(now, prior): an early renewal banks the days left on the
                # current term instead of restarting it at today.
                new = max(moment, prior) + days * 86400.0
                conn.execute("UPDATE user_accounts SET vip_until = ? WHERE id = ?",
                             (new, int(row["account_id"])))
            marked = conn.execute(
                "UPDATE payment_transactions SET status = ?, reviewed_at = ?,"
                " reviewer_note = ? WHERE id = ? AND status = ?",
                (action, moment, why or None, int(payment_id), STATUS_PENDING))
            if marked.rowcount != 1:
                # Another reviewer closed it between our read and our write.
                if owns:
                    _rollback(conn)
                raise PaymentNotFound()
            conn.execute(
                "INSERT INTO payment_review_audit(payment_id, account_id, action,"
                " prior_vip_until, new_vip_until, reviewer, note, acted_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (int(payment_id), int(row["account_id"]), action, prior, new,
                 who, why or None, moment))
            if owns:
                conn.commit()
        except accounts.AccountError:
            if owns:
                _rollback(conn)
            raise
        except sqlite3.Error as error:
            if owns:
                _rollback(conn)
            raise _ledger_unavailable() from error
    return {"payment_id": int(payment_id), "status": action, "changed": True,
            "account_id": int(row["account_id"]), "vip_until": new,
            "prior_vip_until": prior, "days": days, "reviewed_at": moment}


def approve_payment(conn_or_path, payment_id, *, reviewer="", note="",
                    now: float | None = None, catalog_path=None) -> dict:
    """Credit the plan's days to the payer and close the row as `approved`.

    The credit is `max(now, vip_until) + days(plan)` written in the same
    transaction as the status change, so there is no window in which a payment is
    marked approved and the user is not VIP, and none in which a user is VIP and
    the ledger still says `pending`. An unknown plan raises rather than defaulting
    to 30 days: a credit nobody priced is a credit nobody can explain."""
    identifier = _positive_id(payment_id)
    # The plan's length is fixed by the plan, not by the row's amount, so it is
    # read before the transaction opens: a price table we cannot read must never
    # half-apply a credit.
    with accounts._borrow(conn_or_path) as conn:
        row = _payment_row(conn, identifier)
    if row is None:
        raise PaymentNotFound()
    days = plan_days(row["plan"])
    if days <= 0:
        raise PaymentError("that plan has no credit length")
    return _review(conn, identifier, action=STATUS_APPROVED, reviewer=reviewer,
                   note=note, now=now, credit_days=days)


def reject_payment(conn_or_path, payment_id, *, reviewer="", note="",
                   now: float | None = None) -> dict:
    """Close the row as `rejected`. `vip_until` is not read for writing and not
    written: a reject cannot shorten, reset or extend a membership, whatever else
    the account row says."""
    identifier = _positive_id(payment_id)
    return _review(conn_or_path, identifier, action=STATUS_REJECTED,
                   reviewer=reviewer, note=note, now=now, credit_days=None)


def _positive_id(payment_id) -> int:
    try:
        number = int(payment_id)
    except (TypeError, ValueError):
        raise InvalidPayment("payment id must be a number") from None
    if number < 1:
        raise InvalidPayment("payment id must be a number")
    return number


# ── reads ────────────────────────────────────────────────────────────────────

def has_pending(conn_or_path, account_id) -> bool:
    """Does this account have a claim a human has not closed yet?"""
    with accounts._borrow(conn_or_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM payment_transactions WHERE account_id = ? AND status = ?"
            " LIMIT 1", (int(account_id), STATUS_PENDING)).fetchone()
    return row is not None


def entitlement(conn_or_path, key, *, now: float | None = None,
                tracker: accounts.AttemptTracker | None = None) -> dict:
    """The payer's own answer about their own account: `vip`, `vip_until`,
    `pending`. Three keys, built by hand.

    Goes through `accounts.authenticate`, so a wrong key, a revoked key and a key
    that never existed stay indistinguishable, and a hammering caller burns its
    attempt budget exactly as it would on the favorites routes. `pending` is the
    ONLY payment fact an account may learn about itself, and it is a boolean: the
    response says nothing about any TID, any other account, or what the operator
    typed in a note."""
    moment = time.time() if now is None else float(now)
    with accounts._borrow(conn_or_path) as conn:
        account = accounts._authenticate(conn, key, now=moment, tracker=tracker)
        pending = has_pending(conn, account["account_id"])
    return {"vip": bool(account["vip_until"] > moment),
            "vip_until": float(account["vip_until"] or 0), "pending": bool(pending)}


def list_payments(conn_or_path, *, status: str | None = STATUS_PENDING,
                  limit: int = 50) -> list[dict]:
    """Ledger rows for the operator screen, oldest claim first (the queue is a
    queue). `status=None` lists the most recent of every state, which is what the
    page shows under the pending list so a rejected payer can be explained.

    The rows carry a raw `tid` and therefore belong on the loopback surface only
    (`admin_panel._gate` + `viewer.OPERATOR_ONLY_PREFIXES`); `hint` is the
    printable fingerprint, `key_hash` is fetched only to build it and is never
    returned."""
    wanted = max(1, min(int(limit), MAX_LEDGER_ROWS))
    columns = ", ".join("p." + name for name in _PAYMENT_COLUMNS)
    if status is None:
        sql = (f"SELECT {columns}, a.key_hash AS source_hash"
               " FROM payment_transactions p"
               " LEFT JOIN user_accounts a ON a.id = p.account_id"
               " ORDER BY p.submitted_at DESC LIMIT ?")
    else:
        sql = (f"SELECT {columns}, a.key_hash AS source_hash"
               " FROM payment_transactions p"
               " LEFT JOIN user_accounts a ON a.id = p.account_id"
               " WHERE p.status = ? ORDER BY p.submitted_at ASC LIMIT ?")
    params = (wanted,) if status is None else (str(status), wanted)
    with accounts._borrow(conn_or_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        out.append({
            "payment_id": int(row["id"]),
            "hint": account_hint(row["source_hash"]),
            "plan": str(row["plan"] or ""),
            "amount_pkr": int(row["amount_pkr"] or 0),
            "method": str(row["method"] or ""),
            "tid": str(row["tid"] or ""),
            "status": str(row["status"] or ""),
            "submitted_at": float(row["submitted_at"] or 0),
            "reviewed_at": float(row["reviewed_at"] or 0),
            "reviewer_note": str(row["reviewer_note"] or ""),
        })
    return out


def pending_count(conn_or_path) -> int:
    with accounts._borrow(conn_or_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM payment_transactions"
                           " WHERE status = ?", (STATUS_PENDING,)).fetchone()
    return int(row[0]) if row else 0


def payment(conn_or_path, payment_id) -> dict | None:
    """One row, for the route that must say what it just did without re-reading
    the whole queue. `None` when there is no such row."""
    identifier = _positive_id(payment_id)
    with accounts._borrow(conn_or_path) as conn:
        row = _payment_row(conn, identifier)
    if row is None:
        return None
    return {
        "payment_id": int(row["id"]), "account_id": int(row["account_id"]),
        "plan": str(row["plan"] or ""), "amount_pkr": int(row["amount_pkr"] or 0),
        "method": str(row["method"] or ""), "status": str(row["status"] or ""),
        "submitted_at": float(row["submitted_at"] or 0),
        "reviewed_at": float(row["reviewed_at"] or 0),
        "reviewer_note": str(row["reviewer_note"] or ""),
    }


def audit_for(conn_or_path, payment_id, *, limit: int = 10) -> list[dict]:
    """The review history of one row, for the operator screen. Never a TID, never
    a key: an audit trail is read by people who should not need payment
    artifacts to understand a credit."""
    with accounts._borrow(conn_or_path) as conn:
        rows = conn.execute(
            "SELECT %s FROM payment_review_audit WHERE payment_id = ?"
            " ORDER BY acted_at DESC LIMIT ?"
            % ", ".join(_AUDIT_COLUMNS), (int(payment_id), max(1, min(int(limit), 50)))
        ).fetchall()
    return [{"payment_id": int(row["payment_id"]), "action": str(row["action"]),
             "prior_vip_until": float(row["prior_vip_until"] or 0),
             "new_vip_until": float(row["new_vip_until"] or 0),
             "reviewer": str(row["reviewer"] or ""),
             "note": str(row["note"] or ""), "acted_at": float(row["acted_at"] or 0)}
            for row in rows]


def _selfcheck() -> int:
    """`python3 -S Fast_Fetch/payments.py` — a temp file, no port, real round trip."""
    import tempfile
    from contextlib import closing

    with tempfile.TemporaryDirectory() as work:
        state = Path(work) / "user_state.db"
        with closing(accounts.connect(state)) as conn:
            made = accounts.create_account(conn, key="x" * 20)
            account_id = made["account_id"]
            filed = submit_payment(conn, account_id, plan="vip_monthly",
                                   method="jazzcash", tid="9823145671")
            assert filed["status"] == STATUS_PENDING and filed["amount_pkr"] == 250
            assert has_pending(conn, account_id)
            approved = approve_payment(conn, filed["payment_id"], reviewer="selfcheck")
            assert approved["changed"] and approved["days"] == 30, approved
            assert not has_pending(conn, account_id)
            again = approve_payment(conn, filed["payment_id"], reviewer="selfcheck")
            assert not again["changed"] and again["vip_until"] == approved["vip_until"]
            assert accounts.vip_status(state, "x" * 20)["vip"] is True
        print("[.] payments selfcheck OK — pending, approved, replayed, VIP")
        return 0


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
