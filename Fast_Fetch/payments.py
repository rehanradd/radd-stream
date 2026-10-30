#!/usr/bin/env python3
"""
Fast_Fetch/payments.py — the JazzCash / EasyPaisa / Raast ledger and the VIP
entitlement it buys. Stdlib only.
════════════════════════════════════════════════════════════════════════════════════
WHAT THIS IS (docs/FULL_MASTER_FEATURE_INVENTORY.md §M-MON-01)
--------------------------------------------------------------------------------
A user can pay; until this module nothing could ever *become* VIP. The host has no
payment gateway and no TLS, so the ledger's default answer is a claim a human owns:

  1. the app shows the operator's payment handles (`/api/v1/app/remote-config`,
     built by `admin_panel.remote_config`) and the user sends PKR out-of-band;
  2. the user posts the transaction id here — `submit_payment()` — which stores
     it as `pending` against a price the SERVER chose, never one the client sent;
  3. the operator reads the SMS and approves or rejects on `/admin/payments`
     (`admin_panel`, loopback only);
  4. approval is what writes `user_accounts.vip_until`. Nothing else does.

A relay that forwards that bank SMS to `POST /api/v2/payment/sms-webhook`
(`sms_webhook()`) is the same fact arriving as a request, and it changes step 3 for
exactly one class of row: a claim whose TID, gateway and amount all match what the
relay reported is closed by `approve_payment()` with `reviewer="radd-relay"`, and
money that arrives *before* its claim is filed in `verified_incoming_tids` until
`submit_payment()` can spend it. Every other row still waits for a human. What the
relay changes is the queue, not the meaning of a status: `status` is still the whole
difference between a claim and an entitlement, `pending` is still never VIP, and a
callback proves that somebody holds `RADD_MERCHANT_SECRET` — not that a bank
accepted a payment.

WHAT THIS IS NOT
--------------------------------------------------------------------------------
* **Not a payment processor.** No money moves here, no card data, no gateway
  credential, no 3-D Secure. A TID pasted into this endpoint proves nothing except
  that somebody typed it — which is why the default answer is `pending` and why the
  only paths to VIP are a human who checked their own SMS and a relay that holds the
  merchant secret and reported the exact amount THIS server quoted for that claim.
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
* `RADD_MERCHANT_SECRET` follows the `RADD_ADMIN_TOKEN` convention exactly: the
  value belongs to the owner, lives in the process environment, appears in no file,
  no row, no response and no log, and is compared with `hmac.compare_digest`. An
  unset secret authorises no caller at all — see `merchant_authorized`.
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
import hmac
import os
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

import accounts

# ── the plan table (the ONLY thing that decides a price) ─────────────────────
#: plan -> (default PKR, VIP days). Days, not months: `vip_until` is epoch
#: seconds and a 30-day month is what a renewal arithmetic can actually do.
#: PKR 200/month and PKR 1,500/year are `PAKISTAN_OPERATOR_GUIDE.md`'s own
#: numbers; the yearly default is the guide's, the monthly default is the
#: operator's editable one (`app_remote_config.vip_monthly_pkr`), and a saved
#: price wins over these figures whenever that row can be read.
PLAN_DEFAULTS = {
    "vip_monthly": (200, 30),
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
            # Instant validation: if the relay already reported THIS transaction id
            # at this price, the money is not a claim any more and the payer should
            # not wait for a human who is asleep. Nothing about a credit that could
            # not be applied may undo the claim — the row is committed, and a
            # `PaymentError` here (a revoked account, a row that closed under us)
            # leaves the claim `pending` for the operator, which is exactly what
            # every unverified claim was before this existed.
            status = STATUS_PENDING
            record = _verified_incoming(conn, way, reference, now=moment)
            if record is not None:
                try:
                    outcome = _credit_from_relay(conn, payment_id=payment_id,
                                                 gateway=way, reference=reference,
                                                 paid=record["amount_pkr"],
                                                 now=moment)
                    if outcome["approved"]:
                        status = STATUS_APPROVED
                except PaymentError:
                    status = STATUS_PENDING
        except accounts.Locked:
            raise
        except sqlite3.Error as error:
            if owns:
                _rollback(conn)
            raise _ledger_unavailable() from error
    return {"payment_id": payment_id, "status": status, "plan": name,
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


# ── the SMS relay: money the phone saw before the claim did ──────────────────
#
# `PAKISTAN_OPERATOR_GUIDE.md`'s flow was "the operator reads the SMS on their own
# phone". A relay that forwards that SMS here is the same fact arriving as a
# request, and it changes exactly one thing: the ledger can stop guessing. The
# flow therefore splits in two, and both halves are priced by the server:
#
#   money arrives, no claim yet  -> `verified_incoming_tids` gets one row
#   claim arrives, TID known     -> the claim is credited without a human
#
# What the relay does NOT get to decide is who the money belongs to. There is no
# account in a bank SMS this server can read, so a TID is a bearer instrument:
# whoever files the claim first spends the credit. `verify_merchant_header` is
# what keeps that instrument out of a stranger's hands, the amount equality below
# is what keeps a PKR 50 partial payment from buying a year, and
# `_claim_already_credited` is what keeps one payment from buying two memberships.
# The residual — somebody who steals a TID and files it before its real payer, which
# this design cannot see and nginx cannot help with — is why the automatic path is
# allowed ONLY on an exact three-way match and why a human still owns every row the
# relay cannot match that precisely.

#: The header the relay signs its callback with, and the environment variable that
#: holds the shared secret. Same convention as `RADD_ADMIN_TOKEN`: the value is the
#: owner's, lives in the process environment, and is never in a file, a row, or a
#: log. An unset secret authorises NOTHING — see `verify_merchant_header`.
MERCHANT_SECRET_HEADER = "X-Merchant-Secret"
MERCHANT_SECRET_ENV = "RADD_MERCHANT_SECRET"
#: The reviewer string on the audit row of a relay credit. It is a *label*, not a
#: person, and it has to be distinguishable five hundred rows from now: "who
#: approved this?" is answered here, and the answer must not be "the operator, who
#: was asleep".
RELAY_REVIEWER = "radd-relay"
#: The route the merchant posts to, declared beside the logic that answers it so a
#: mount and the module cannot drift apart on the path money arrives on. NOTE: this
#: is under `/api/v2/` but NOT under `/api/v2/account`, and nginx allow-lists the
#: account prefix and 403s the rest of `/api/` — and that 403 is the CONTROL, not a
#: gap. `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R1-R2 ruled it: this host is
#: plain HTTP, so a static long-lived `X-Merchant-Secret` posted here from the
#: operator's phone over Pakistani mobile data would cross the network in the clear
#: to anyone on the path, and whoever sniffed it could approve their own VIP
#: indefinitely on our bill. The sanctioned transport is an **outbound SSH tunnel
#: from the operator's phone** (`autossh -M 0 -N -L 127.0.0.1:8099:127.0.0.1:8080
#: ubuntu@<host>`, relay POSTs to `http://127.0.0.1:8099` + this path), which buys
#: encryption and device authentication in one move for $0 and needs no new listener
#: and no edge change. Opening a public `location` for this path would be the wrong
#: fix, so nothing here asks for one.
WEBHOOK_PATH = "/api/v2/payment/sms-webhook"
#: How stale a relay record may be and still credit a claim. A payer who sends the
#: money and files the claim a month later is not the same event as one who files
#: it in the next minute, and a "verified" row older than this is a thing a human
#: should look at, not a thing a machine should act on.
VERIFIED_TID_MAX_AGE_SECONDS = 7 * 86400.0


def _clean_gateway(gateway) -> str:
    """The network the relay says moved the money, in the ledger's own vocabulary.
    `METHODS`/`TID_SHAPES` already decide what a method is called; a second list of
    gateway spellings here would be a second answer to the same question, so a
    relay that says `JazzCash ` normalizes to `jazzcash` and anything else is
    refused rather than stored as prose."""
    name = str(gateway or "").strip().lower()
    if name not in TID_SHAPES:
        raise InvalidPayment("unknown gateway")
    return name


def _clean_amount(value):
    """PKR as an int, or `None`. A relay that reports `Rs. 250` sends 250 or "250";
    a fractional amount is refused rather than truncated, because PKR has no
    smaller unit and a body that says 250.50 is a body nobody can explain.
    `bool` is excluded by `_pkr` for the reason it always was: a column holding
    `1` where a price should be is a mistake, not PKR 1."""
    if isinstance(value, float) and not value.is_integer():
        return None
    return _pkr(value)


def merchant_authorized(presented, *, env=None) -> bool:
    """Does this value match the owner's merchant secret?

    Constant-time, and `False` when the secret is unset, empty, or the presented
    value is not a string. The unset case is the important one: a deployment that
    forgot `RADD_MERCHANT_SECRET` must not be able to credit memberships for
    whoever knocks, so no secret means no caller is the merchant. There is no
    "default secret" and no warning-and-continue path here.

    `env` is the mapping to read the secret from — `os.environ` by default and a
    dict in a test, because a credential that can only be exercised by mutating the
    process environment is a credential nobody tests."""
    source = os.environ if env is None else env
    wanted = str(source.get(MERCHANT_SECRET_ENV, "") or "").strip()
    if not wanted or not isinstance(presented, str):
        return False
    return hmac.compare_digest(presented.strip(), wanted)


def verify_merchant_header(headers, *, env=None) -> bool:
    """The same answer, read straight off a request's headers — the mount's whole
    authorization decision, kept here so the header name, the environment name and
    the fail-closed rule live next to the money they protect.

    `headers` is any mapping with `.get` (an `http.client.HTTPMessage`, a dict in a
    test). A duplicate header collapses to the first value in both cases, and one
    of two different secrets is not a caller we should be crediting anything for,
    so a mismatched pair simply fails."""
    return merchant_authorized((headers or {}).get(MERCHANT_SECRET_HEADER, ""),
                               env=env)


def _rows_for_tid(conn, reference: str) -> list:
    """Every ledger row that carries this TID, oldest claim first.

    A TID has no unique index, and adding one to a live table that may already hold
    duplicates is a migration, not a `CREATE UNIQUE INDEX` — so the rule is enforced
    by reading instead: one payment may appear in several claims, and it may buy
    exactly one of them."""
    return conn.execute(
        "SELECT %s FROM payment_transactions WHERE tid = ?"
        " ORDER BY submitted_at ASC" % ", ".join(_PAYMENT_COLUMNS),
        (reference,)).fetchall()


def _claim_already_credited(conn, reference: str) -> bool:
    """Has this TID already bought a membership? The one question that must be
    answered before any second credit, from either path — the relay replaying its
    own SMS, or a second account filing the same reference."""
    return conn.execute(
        "SELECT 1 FROM payment_transactions WHERE tid = ? AND status = ? LIMIT 1",
        (reference, STATUS_APPROVED)).fetchone() is not None


def _verified_incoming(conn, gateway: str, reference: str, *, now: float) -> dict | None:
    """The relay's record of this payment, if there is a live one.

    `None` covers three cases the caller must treat the same way — never seen, too
    old to act on, and no table yet — and the third is why this read swallows
    `sqlite3.Error`: `verified_incoming_tids` is new, and a state file that predates
    it holds no relay money. Answering that with a 500 would make an ordinary claim
    fail; answering it with "not verified" sends the claim to a human, which is what
    every unverified claim already did. Failing toward the human is the only safe
    direction when the thing you cannot read is a payment."""
    try:
        row = conn.execute(
            "SELECT amount_pkr, verified_at FROM verified_incoming_tids"
            " WHERE gateway = ? AND tid = ?", (gateway, reference)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    verified_at = float(row["verified_at"] or 0)
    if now - verified_at > VERIFIED_TID_MAX_AGE_SECONDS:
        return None
    return {"amount_pkr": int(row["amount_pkr"] or 0), "verified_at": verified_at}


def _consume_verified(conn, gateway: str, reference: str) -> None:
    """Delete the relay record that just bought a credit.

    Spent, not flagged: the row's only permitted use is to credit one claim, and a
    record left behind is a record a second claim can spend. If the process dies
    between the credit and this delete, `_claim_already_credited` is what stops the
    next caller, so the worst a lost delete can do is show the operator a stale
    unclaimed row."""
    try:
        conn.execute("DELETE FROM verified_incoming_tids WHERE gateway = ? AND tid = ?",
                     (gateway, reference))
        accounts._commit(conn)
    except sqlite3.Error:
        pass


def _credit_from_relay(conn, *, payment_id, gateway: str, reference: str,
                       paid, now: float) -> dict:
    """Close one claim as approved because the relay says the money is there.

    `paid` is what the relay reports arrived — the amount in this callback's body,
    or the amount filed by the callback that landed before the claim (that is what
    `submit_payment` passes). It is compared against the claim row's own
    `amount_pkr`, which is the price THIS server quoted, so a credit buys the plan
    the payer was charged for and never whatever the SMS happened to print. A PKR 50
    partial payment against a PKR 1500 yearly claim is an `amount-mismatch`, and an
    `amount-mismatch` is an operator's decision, not a machine's.

    Three conditions, all of them about money rather than about eagerness to be
    automatic: the TID has bought nothing yet, the gateway in the callback is the
    gateway the claim names, and the two amounts are the same integer. Anything else
    returns `approved: False` and leaves the row `pending`, which is the pre-existing
    behavior and never a loss — a claim a human approves is a payer who waits an
    hour longer, and a claim a machine approves on a mismatched amount is a year of
    VIP for PKR 10.
    """
    if _claim_already_credited(conn, reference):
        return {"approved": False, "reason": "already-credited"}
    row = _payment_row(conn, payment_id)
    if row is None:
        return {"approved": False, "reason": "not-verified"}
    if str(row["method"] or "") != gateway:
        # The claim says Raast and the SMS says JazzCash: one of the two is a typo
        # or a lie, and neither is a reason to credit anything.
        return {"approved": False, "reason": "gateway-mismatch"}
    price = int(row["amount_pkr"] or 0)
    seen = _clean_amount(paid)
    if seen is None:
        return {"approved": False, "reason": "no-amount"}
    if price <= 0 or seen != price:
        return {"approved": False, "reason": "amount-mismatch"}
    result = approve_payment(conn, payment_id, reviewer=RELAY_REVIEWER,
                             note="relay confirmed PKR %d on %s" % (price, gateway),
                             now=now)
    if not result.get("changed"):
        return {"approved": False, "reason": "already-credited"}
    _consume_verified(conn, gateway, reference)
    return {"approved": True, "reason": "credited"}


def sms_webhook(conn_or_path, *, gateway, tid, amount=None,
                now: float | None = None) -> dict:
    """Money the relay read out of a bank SMS: credit the claim it matches, or file
    the fact until a claim arrives.

    `gateway` is the network, `tid` the reference the SMS printed, `amount` the PKR
    it says arrived. Nothing identifies a payer, because a bank SMS as delivered
    here does not either — this is why the amount has to be believed and checked,
    and why the credit goes to whichever account filed the matching claim.

    Answers `{"verified", "matched", "approved", "recorded", "reason"}` and no
    account id, no amount and no TID: the relay already knows all three, and this
    response travels the same plain-HTTP wire as everything else on this host.
    `matched` says a ledger row carries this TID, `approved` says THIS call closed
    it, `recorded` says THIS call filed a new `verified_incoming_tids` row, and
    `verified` says the server now treats the money as confirmed for a claim it can
    act on. A `reason` is a machine word (`credited`, `amount-mismatch`,
    `already-credited`, `gateway-mismatch`, `not-verified`, `no-amount`,
    `recorded`, `already-recorded`) so a relay can log it and an operator can grep
    it, and it is not a sentence about anybody's money.

    Replay-safe by construction: a second callback for a TID that already bought a
    membership approves nothing, and the same SMS arriving before and after a claim
    lands the credit exactly once (the verified row is consumed by the credit, and
    `_claim_already_credited` is checked on both paths). A replay of the
    file-the-fact branch cannot refresh the clock either: `INSERT OR IGNORE` keeps
    the ORIGINAL `verified_at`, so replaying an SMS does not buy the record a second
    week of validity."""
    network = _clean_gateway(gateway)
    reference = _clean_tid(network, tid)
    paid = _clean_amount(amount)
    moment = time.time() if now is None else float(now)
    with accounts._borrow(conn_or_path) as conn:
        rows = _rows_for_tid(conn, reference)
        if any(str(row["status"]) == STATUS_APPROVED for row in rows):
            return {"verified": True, "matched": True, "approved": False,
                    "recorded": False, "reason": "already-credited"}
        pending = [row for row in rows if str(row["status"]) == STATUS_PENDING]
        if pending:
            # The claim is already in the ledger, so this callback IS the
            # verification and needs no earlier record: the common ordering is a
            # payer who submits the form and then watches the SMS arrive.
            out = _credit_from_relay(conn, payment_id=int(pending[0]["id"]),
                                     gateway=network, reference=reference,
                                     paid=paid, now=moment)
            return {"verified": out["approved"], "matched": True,
                    "approved": out["approved"], "recorded": False,
                    "reason": out["reason"]}
        if paid is None:
            # No claim and no amount is not a fact worth filing: the whole value of
            # the record is that a later claim can be checked against a price.
            return {"verified": False, "matched": False, "approved": False,
                    "recorded": False, "reason": "no-amount"}
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO verified_incoming_tids(gateway, tid,"
                " amount_pkr, verified_at) VALUES(?, ?, ?, ?)",
                (network, reference, paid, moment))
            accounts._commit(conn)
        except sqlite3.Error as error:
            raise _ledger_unavailable() from error
        return {"verified": True, "matched": False, "approved": False,
                "recorded": bool(cur.rowcount),
                "reason": "recorded" if cur.rowcount else "already-recorded"}


def unclaimed_credits(conn_or_path, *, limit: int = 50) -> list[dict]:
    """Relay-confirmed money that has bought nothing, oldest first — the operator's
    list of payments that arrived and nobody has collected.

    It is `admin_panel` data and it carries raw TIDs, so it belongs on the loopback
    surface beside the queue it explains. A record is excluded only when the ledger
    holds an APPROVED claim for that same TID on that same network: a record whose
    claim is still pending is unspent and the operator is exactly the person who has
    to see it, because "the SMS says PKR 50 and the claim says PKR 200" is a
    decision, not a bug. Since a credit deletes its own record, this read is the
    second line of defense against a lost delete rather than the normal way a spent
    row disappears."""
    wanted = max(1, min(int(limit), MAX_LEDGER_ROWS))
    try:
        with accounts._borrow(conn_or_path) as conn:
            rows = conn.execute(
                "SELECT gateway, tid, amount_pkr, verified_at FROM"
                " verified_incoming_tids v WHERE NOT EXISTS"
                " (SELECT 1 FROM payment_transactions p"
                "  WHERE p.tid = v.tid AND p.method = v.gateway"
                "   AND p.status = ?)"
                " ORDER BY v.verified_at ASC LIMIT ?",
                (STATUS_APPROVED, wanted)).fetchall()
    except sqlite3.Error:
        return []
    return [{"gateway": str(row["gateway"] or ""), "tid": str(row["tid"] or ""),
             "amount_pkr": int(row["amount_pkr"] or 0),
             "verified_at": float(row["verified_at"] or 0)} for row in rows]


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
            assert filed["status"] == STATUS_PENDING and filed["amount_pkr"] == 200
            assert has_pending(conn, account_id)
            approved = approve_payment(conn, filed["payment_id"], reviewer="selfcheck")
            assert approved["changed"] and approved["days"] == 30, approved
            assert not has_pending(conn, account_id)
            again = approve_payment(conn, filed["payment_id"], reviewer="selfcheck")
            assert not again["changed"] and again["vip_until"] == approved["vip_until"]
            assert accounts.vip_status(state, "x" * 20)["vip"] is True
            # ── the relay: money first, claim second, one credit only ──────────
            assert merchant_authorized("s3cret", env={MERCHANT_SECRET_ENV: "s3cret"})
            assert not merchant_authorized("s3cret", env={})
            assert not merchant_authorized(None, env={MERCHANT_SECRET_ENV: "s3cret"})
            early = accounts.create_account(conn, key="y" * 20)["account_id"]
            filed = sms_webhook(conn, gateway="jazzcash", tid="9823145672", amount=200)
            assert filed["recorded"] and filed["reason"] == "recorded", filed
            assert [row["tid"] for row in unclaimed_credits(conn)] == ["9823145672"]
            claim = submit_payment(conn, early, plan="vip_monthly",
                                   method="jazzcash", tid="9823145672")
            assert claim["status"] == STATUS_APPROVED, claim
            assert accounts.vip_status(state, "y" * 20)["vip"] is True
            assert unclaimed_credits(conn) == []          # spent, not flagged
            replay = sms_webhook(conn, gateway="jazzcash", tid="9823145672",
                                 amount=200)
            assert not replay["approved"] and replay["reason"] == "already-credited"
            thief = accounts.create_account(conn, key="z" * 20)["account_id"]
            stolen = submit_payment(conn, thief, plan="vip_monthly",
                                    method="jazzcash", tid="9823145672")
            assert stolen["status"] == STATUS_PENDING, stolen
            late = accounts.create_account(conn, key="w" * 20)["account_id"]
            half = sms_webhook(conn, gateway="easypaisa", tid="9823145673", amount=50)
            assert half["recorded"], half
            underpaid = submit_payment(conn, late, plan="vip_monthly",
                                       method="easypaisa", tid="9823145673")
            assert underpaid["status"] == STATUS_PENDING, underpaid
            assert not accounts.vip_status(state, "w" * 20)["vip"]
            ahead = submit_payment(conn, late, plan="vip_yearly", method="raast",
                                   tid="ABCDEFGH123456", min_interval=0.0)
            assert ahead["status"] == STATUS_PENDING and ahead["amount_pkr"] == 1500
            now_claim = sms_webhook(conn, gateway="raast", tid="ABCDEFGH123456",
                                    amount=1500)
            assert now_claim["approved"] and now_claim["reason"] == "credited", now_claim
        print("[.] payments selfcheck OK — pending, approved, replayed, VIP, and the"
              " relay credited one claim and refused a replay, a theft and a partial")
        return 0


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
