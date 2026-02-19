"""Matching engine - matches checkout journey payment intents against transaction paya_references.

Uses set-based O(1) lookup for maximum speed. Thread pool for parallel client processing.
"""

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from utils.logger import log
from core.fetcher import ClientData


@dataclass
class MatchResult:
    client_name: str
    matched: list[dict] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    matched_count: int = 0
    unmatched_count: int = 0
    total_checkouts: int = 0
    total_transactions: int = 0
    match_rate: float = 0.0
    error: str | None = None


def match_client(client_data: ClientData) -> MatchResult:
    """Match a single client's checkout journeys against transactions.

    Strategy:
    - Build a set of paya_references from transactions (O(1) lookup)
    - For each checkout, check if stripe_payment_intent_id exists in paya_references
    - Matched → verified transaction, remove from working set
    - Unmatched → needs attention, kept for reporting
    """
    result = MatchResult(client_name=client_data.client_name)

    if client_data.error:
        result.error = client_data.error
        return result

    result.total_checkouts = client_data.checkout_count
    result.total_transactions = client_data.transaction_count

    # Build lookup set from transactions - O(n)
    paya_ref_set = {
        txn["paya_reference"]
        for txn in client_data.transactions
        if txn.get("paya_reference")
    }

    # Build lookup dict for transaction details (for matched records)
    txn_by_ref = {}
    for txn in client_data.transactions:
        ref = txn.get("paya_reference")
        if ref:
            txn_by_ref[ref] = txn

    # Free original transaction list from memory
    client_data.transactions = []

    # Match each checkout - O(n) with O(1) lookups
    for checkout in client_data.checkouts:
        pi = checkout.get("stripe_payment_intent_id", "")
        if not pi:
            continue

        if pi in paya_ref_set:
            # Matched - combine checkout + transaction data
            txn = txn_by_ref.get(pi, {})
            matched_record = {
                "checkout": checkout,
                "transaction": txn,
                "payment_intent": pi,
            }
            result.matched.append(matched_record)
            paya_ref_set.discard(pi)  # Remove from set (memory management)
        else:
            result.unmatched.append(checkout)

    # Free checkout list from memory
    client_data.checkouts = []

    result.matched_count = len(result.matched)
    result.unmatched_count = len(result.unmatched)

    total = result.matched_count + result.unmatched_count
    result.match_rate = (result.matched_count / total * 100) if total > 0 else 0.0

    log.info(
        f"[{client_data.client_name}] Matched: {result.matched_count}, "
        f"Unmatched: {result.unmatched_count}, Rate: {result.match_rate:.1f}%"
    )

    return result


def match_all_clients(
    clients_data: list[ClientData], max_workers: int = 4
) -> list[MatchResult]:
    """Match all clients using thread pool for parallel processing."""
    log.info(f"Starting matching for {len(clients_data)} clients (workers={max_workers})...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(match_client, clients_data))

    total_matched = sum(r.matched_count for r in results)
    total_unmatched = sum(r.unmatched_count for r in results)
    log.info(f"Matching complete: {total_matched} matched, {total_unmatched} unmatched across all clients")

    return results
