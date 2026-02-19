"""Async data fetcher - pulls checkout journey and transaction data from client APIs."""

import asyncio
import aiohttp
from dataclasses import dataclass, field
from utils.logger import log
from config.settings import ClientConfig, AppSettings


@dataclass
class ClientData:
    client_name: str
    checkouts: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)
    checkout_count: int = 0
    transaction_count: int = 0
    error: str | None = None


async def _fetch_paginated(
    session: aiohttp.ClientSession,
    url: str,
    api_key: str,
    days: int,
    page_size: int,
    timeout: int,
) -> list[dict]:
    """Fetch all pages from a paginated API endpoint."""
    all_data = []
    page = 1

    while True:
        params = {"days": days, "page": page, "limit": page_size}
        headers = {"X-Api-Key": api_key}

        async with session.get(
            url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status} from {url}")

            body = await resp.json()

            if not body.get("success"):
                raise Exception(f"API error: {body.get('error', 'Unknown')}")

            data = body.get("data", [])
            all_data.extend(data)

            if not body.get("has_more", False):
                break

            page += 1

    return all_data


async def fetch_client_data(
    client: ClientConfig, settings: AppSettings
) -> ClientData:
    """Fetch checkout journey and transaction data for a single client."""
    result = ClientData(client_name=client.name)
    base = client.base_url.rstrip("/")

    try:
        async with aiohttp.ClientSession() as session:
            checkout_url = f"{base}/get_checkout_journey.php"
            txn_url = f"{base}/get_transactions.php"

            log.info(f"[{client.name}] Fetching data (last {settings.days} days)...")

            # Fetch both endpoints concurrently for this client
            checkouts_task = _fetch_paginated(
                session, checkout_url, client.api_key,
                settings.days, settings.fetch_page_size, settings.request_timeout,
            )
            txns_task = _fetch_paginated(
                session, txn_url, client.api_key,
                settings.days, settings.fetch_page_size, settings.request_timeout,
            )

            checkouts, txns = await asyncio.gather(checkouts_task, txns_task)

            result.checkouts = checkouts
            result.transactions = txns
            result.checkout_count = len(checkouts)
            result.transaction_count = len(txns)

            log.info(
                f"[{client.name}] Fetched {result.checkout_count} checkouts, "
                f"{result.transaction_count} transactions"
            )

    except Exception as e:
        result.error = str(e)
        log.error(f"[{client.name}] Fetch failed: {e}")

    return result


async def fetch_all_clients(settings: AppSettings) -> list[ClientData]:
    """Fetch data from all enabled clients concurrently."""
    log.info(f"Starting fetch for {len(settings.clients)} clients...")

    tasks = [fetch_client_data(client, settings) for client in settings.clients]
    results = await asyncio.gather(*tasks)

    success = sum(1 for r in results if r.error is None)
    log.info(f"Fetch complete: {success}/{len(results)} clients successful")

    return list(results)
