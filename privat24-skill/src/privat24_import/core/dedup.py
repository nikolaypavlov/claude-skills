"""Transaction-id generation for Privat24 rows.

Privat24 web XLSX exports carry no stable reference id, so we synthesise a
SHA-256-based id from the row's natural fields. Two imports that overlap
in date range (re-export to widen the window) must dedupe correctly - the
hash therefore depends ONLY on natural fields, NOT on the row index or
file content hash. A separate ``file_sha256`` is stored in
``privat_import_runs`` as a fast-path short-circuit so the SAME file
imported twice never even hits the parser.

Twin-transaction tie-break: if two rows in the SAME logical input share
(ts, amount, description, account), we append a within-group counter so
they get distinct ids. The counter resets at the start of every
``assign_ids`` call, so the same input sequence always produces the
same id list - that's what ``test_twin_counter_is_stable_across_independent_calls``
verifies. Cross-file dedupe of twin pairs depends additionally on
Privat24 exporting the same rows in the same relative order within
re-exported date ranges, which we observe in practice but cannot
guarantee from this module alone.

The id format is ``privat_h_<16-hex-chars>``. 16 hex chars = 64 bits of
entropy - one-in-a-billion collisions need ~5e9 rows, far beyond any
personal finance dataset.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, TypedDict


class TxKey(TypedDict):
    ts: int
    amount_minor: int
    description: str
    account_id: str


def file_sha256(path: str) -> str:
    """Stream-hash a file. Used by ``privat_import_runs.file_sha256`` to
    short-circuit re-imports of the exact same byte sequence."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def assign_ids(rows: Iterable[TxKey]) -> list[str]:
    """Yield a stable ``privat_h_*`` id per row in input order.

    Rows sharing a full natural key are tie-broken by a 0-based counter
    so twin transactions don't collide on the same id.
    """
    seen: dict[tuple[int, int, str, str], int] = {}
    ids: list[str] = []
    for r in rows:
        key = (r["ts"], r["amount_minor"], r["description"] or "", r["account_id"])
        n = seen.get(key, 0)
        seen[key] = n + 1
        payload = "|".join(str(p) for p in key) + f"|{n}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        ids.append(f"privat_h_{digest}")
    return ids
