"""Data Matcher - Multi-client payment reconciliation system.

FastAPI backend with async data fetching, set-based matching, and analytics dashboard.
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import load_config, load_config_raw, save_config_raw, AppSettings
from core.fetcher import fetch_all_clients, ClientData
from core.matcher import match_all_clients, MatchResult
from core.reporter import generate_reports, send_email_report
from utils.logger import log

# ─── Global State ────────────────────────────────────────────────
app_config: AppSettings = None
last_run: dict | None = None  # Stores latest run results for dashboard
is_running: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_config
    app_config = load_config()
    log.info(f"Loaded config: {len(app_config.clients)} clients, {app_config.days} days lookback")
    yield
    log.info("Shutting down")


app = FastAPI(title="Data Matcher", version="1.0.0", lifespan=lifespan)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ─── Core Matching Pipeline ──────────────────────────────────────
async def run_matching_pipeline(days: int | None = None) -> dict:
    """Execute the full matching pipeline: fetch → match → report."""
    global last_run, is_running, app_config

    if is_running:
        return {"error": "A matching job is already running"}

    is_running = True
    start_time = datetime.now()

    try:
        config = load_config()  # Reload config each run
        if days is not None:
            config.days = days

        # Step 1: Fetch data from all clients (async, concurrent)
        log.info("=" * 60)
        log.info(f"PIPELINE START - {len(config.clients)} clients, {config.days} days")
        log.info("=" * 60)

        clients_data: list[ClientData] = await fetch_all_clients(config)

        # Step 2: Match (thread pool)
        match_results: list[MatchResult] = match_all_clients(
            clients_data, max_workers=config.max_workers
        )

        # Step 3: Generate reports
        report_paths = generate_reports(match_results, max_workers=config.max_workers)

        # Step 4: Email (non-blocking)
        email_sent = send_email_report(config.email, report_paths, match_results)

        elapsed = (datetime.now() - start_time).total_seconds()

        # Build summary for dashboard
        run_summary = {
            "timestamp": start_time.isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "days": config.days,
            "email_sent": email_sent,
            "report_dir": report_paths["dir"],
            "clients": [],
            "totals": {
                "matched": 0,
                "unmatched": 0,
                "errors": 0,
            },
        }

        for r in match_results:
            client_summary = {
                "name": r.client_name,
                "matched": r.matched_count,
                "unmatched": r.unmatched_count,
                "total_checkouts": r.total_checkouts,
                "total_transactions": r.total_transactions,
                "match_rate": round(r.match_rate, 2),
                "error": r.error,
                "unmatched_records": [
                    {
                        "id": c.get("id"),
                        "invoiceid": c.get("invoiceid"),
                        "order_no": c.get("order_no"),
                        "payment_intent": c.get("stripe_payment_intent_id"),
                        "payment_status": c.get("payment_status"),
                        "amount": c.get("total_amount"),
                        "currency": c.get("currency"),
                        "donor_email": c.get("donor_email"),
                        "donor_name": c.get("donor_name"),
                        "created_at": c.get("created_at"),
                    }
                    for c in r.unmatched
                ],
            }
            run_summary["clients"].append(client_summary)
            run_summary["totals"]["matched"] += r.matched_count
            run_summary["totals"]["unmatched"] += r.unmatched_count
            if r.error:
                run_summary["totals"]["errors"] += 1

        last_run = run_summary

        log.info(f"PIPELINE COMPLETE in {elapsed:.2f}s")
        return run_summary

    except Exception as e:
        log.error(f"Pipeline error: {e}")
        return {"error": str(e)}
    finally:
        is_running = False


# ─── API Endpoints ───────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main analytics dashboard."""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "last_run": last_run,
        "is_running": is_running,
        "config": app_config,
    })


@app.post("/api/run")
async def trigger_run(
    background_tasks: BackgroundTasks,
    days: int = Query(default=None, ge=1, le=30),
):
    """Trigger a matching run."""
    if is_running:
        return JSONResponse({"error": "Already running"}, status_code=409)

    # Run in background so the API returns immediately
    async def _run():
        await run_matching_pipeline(days)

    background_tasks.add_task(asyncio.ensure_future, _run())

    # Small delay to let the pipeline start
    await asyncio.sleep(0.1)
    return {"status": "started", "days": days or app_config.days}


@app.post("/api/run-sync")
async def trigger_run_sync(days: int = Query(default=None, ge=1, le=30)):
    """Trigger a matching run and wait for result."""
    result = await run_matching_pipeline(days)
    return result


@app.get("/api/status")
async def get_status():
    """Get current status and last run summary."""
    return {
        "is_running": is_running,
        "last_run": last_run,
        "clients_configured": len(app_config.clients) if app_config else 0,
    }


@app.get("/api/results")
async def get_results():
    """Get last run results."""
    if not last_run:
        return JSONResponse({"error": "No results yet. Run matching first."}, status_code=404)
    return last_run


@app.get("/api/results/{client_name}")
async def get_client_results(client_name: str):
    """Get results for a specific client."""
    if not last_run:
        return JSONResponse({"error": "No results yet"}, status_code=404)

    for client in last_run.get("clients", []):
        if client["name"].lower() == client_name.lower():
            return client

    return JSONResponse({"error": "Client not found"}, status_code=404)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings management page."""
    return templates.TemplateResponse("settings.html", {"request": request})


# ─── Config CRUD API ─────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    """Get full config."""
    return load_config_raw()


@app.put("/api/config/settings")
async def update_settings(request: Request):
    """Update general settings (days, workers, timeout, email)."""
    body = await request.json()
    raw = load_config_raw()
    raw["settings"] = {**raw.get("settings", {}), **body}
    save_config_raw(raw)
    return {"success": True, "settings": raw["settings"]}


@app.get("/api/config/clients")
async def get_clients():
    """Get all clients."""
    raw = load_config_raw()
    return raw.get("clients", [])


@app.post("/api/config/clients")
async def add_client(request: Request):
    """Add a new client."""
    body = await request.json()
    if not body.get("name") or not body.get("base_url"):
        return JSONResponse({"error": "name and base_url are required"}, status_code=400)

    raw = load_config_raw()
    clients = raw.get("clients", [])

    # Check duplicate name
    for c in clients:
        if c["name"].lower() == body["name"].lower():
            return JSONResponse({"error": "Client with this name already exists"}, status_code=409)

    new_client = {
        "name": body["name"],
        "base_url": body["base_url"],
        "api_key": body.get("api_key", ""),
        "table_prefix": body.get("table_prefix", "pw_"),
        "enabled": body.get("enabled", True),
    }
    clients.append(new_client)
    raw["clients"] = clients
    save_config_raw(raw)
    return {"success": True, "client": new_client}


@app.put("/api/config/clients/{client_name}")
async def update_client(client_name: str, request: Request):
    """Update an existing client."""
    body = await request.json()
    raw = load_config_raw()
    clients = raw.get("clients", [])

    for i, c in enumerate(clients):
        if c["name"].lower() == client_name.lower():
            clients[i] = {**c, **body}
            raw["clients"] = clients
            save_config_raw(raw)
            return {"success": True, "client": clients[i]}

    return JSONResponse({"error": "Client not found"}, status_code=404)


@app.delete("/api/config/clients/{client_name}")
async def delete_client(client_name: str):
    """Delete a client."""
    raw = load_config_raw()
    clients = raw.get("clients", [])
    new_clients = [c for c in clients if c["name"].lower() != client_name.lower()]

    if len(new_clients) == len(clients):
        return JSONResponse({"error": "Client not found"}, status_code=404)

    raw["clients"] = new_clients
    save_config_raw(raw)
    return {"success": True}


@app.get("/api/download/{filename}")
async def download_report(filename: str):
    """Download a generated report file."""
    if not last_run:
        return JSONResponse({"error": "No reports available"}, status_code=404)

    report_dir = Path(last_run.get("report_dir", ""))
    file_path = report_dir / filename

    if not file_path.exists() or not file_path.is_relative_to(report_dir):
        return JSONResponse({"error": "File not found"}, status_code=404)

    return FileResponse(file_path, filename=filename)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
