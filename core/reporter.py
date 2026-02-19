"""Report generator - creates CSV/JSON reports and sends email to admin."""

import csv
import json
import smtplib
from io import StringIO
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from utils.logger import log
from config.settings import EmailConfig
from core.matcher import MatchResult

REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def _generate_csv(result: MatchResult) -> str:
    """Generate CSV content for unmatched checkouts."""
    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Client", "Checkout ID", "Invoice ID", "Order No",
        "Payment Intent", "Payment Status", "Amount", "Currency",
        "Donor Email", "Donor Name", "Created At"
    ])

    for checkout in result.unmatched:
        writer.writerow([
            result.client_name,
            checkout.get("id", ""),
            checkout.get("invoiceid", ""),
            checkout.get("order_no", ""),
            checkout.get("stripe_payment_intent_id", ""),
            checkout.get("payment_status", ""),
            checkout.get("total_amount", ""),
            checkout.get("currency", ""),
            checkout.get("donor_email", ""),
            checkout.get("donor_name", ""),
            checkout.get("created_at", ""),
        ])

    return output.getvalue()


def _generate_json(result: MatchResult) -> dict:
    """Generate JSON report for a single client."""
    return {
        "client": result.client_name,
        "summary": {
            "total_checkouts": result.total_checkouts,
            "total_transactions": result.total_transactions,
            "matched": result.matched_count,
            "unmatched": result.unmatched_count,
            "match_rate": round(result.match_rate, 2),
        },
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
            for c in result.unmatched
        ],
    }


def generate_reports(results: list[MatchResult], max_workers: int = 4) -> dict:
    """Generate CSV and JSON reports for all clients. Returns file paths."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPORTS_DIR / timestamp
    run_dir.mkdir(exist_ok=True)

    all_json = []
    csv_files = []

    def process_client(result: MatchResult):
        # CSV for unmatched
        csv_content = _generate_csv(result)
        safe_name = result.client_name.replace(" ", "_").lower()
        csv_path = run_dir / f"{safe_name}_unmatched.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        # JSON report
        json_data = _generate_json(result)

        return csv_path, json_data

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        outputs = list(executor.map(process_client, results))

    for csv_path, json_data in outputs:
        csv_files.append(csv_path)
        all_json.append(json_data)

    # Combined JSON report
    combined = {
        "generated_at": datetime.now().isoformat(),
        "total_clients": len(results),
        "overall_summary": {
            "total_matched": sum(r.matched_count for r in results),
            "total_unmatched": sum(r.unmatched_count for r in results),
            "clients_with_errors": sum(1 for r in results if r.error),
        },
        "clients": all_json,
    }
    json_path = run_dir / "combined_report.json"
    json_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    log.info(f"Reports saved to {run_dir}")

    return {
        "dir": str(run_dir),
        "json_path": str(json_path),
        "csv_files": [str(p) for p in csv_files],
        "combined_json": combined,
    }


def send_email_report(
    email_config: EmailConfig,
    report_paths: dict,
    results: list[MatchResult],
) -> bool:
    """Send email with report attachments to admin."""
    if not email_config.sender_email or not email_config.admin_emails:
        log.warning("Email not configured, skipping send")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = email_config.sender_email
        msg["To"] = ", ".join(email_config.admin_emails)
        msg["Subject"] = f"Data Matcher Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        # Build email body
        total_matched = sum(r.matched_count for r in results)
        total_unmatched = sum(r.unmatched_count for r in results)

        body_lines = [
            "Data Matcher Report",
            "=" * 40,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Clients Processed: {len(results)}",
            f"Total Matched: {total_matched}",
            f"Total Unmatched: {total_unmatched}",
            "",
            "Per Client Summary:",
            "-" * 40,
        ]

        for r in results:
            status = "ERROR" if r.error else "OK"
            body_lines.append(
                f"  {r.client_name}: Matched={r.matched_count}, "
                f"Unmatched={r.unmatched_count}, Rate={r.match_rate:.1f}% [{status}]"
            )

        msg.attach(MIMEText("\n".join(body_lines), "plain"))

        # Attach CSV files
        for csv_path in report_paths.get("csv_files", []):
            path = Path(csv_path)
            if path.exists():
                part = MIMEBase("application", "octet-stream")
                part.set_payload(path.read_bytes())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={path.name}")
                msg.attach(part)

        # Attach JSON report
        json_path = report_paths.get("json_path")
        if json_path and Path(json_path).exists():
            part = MIMEBase("application", "octet-stream")
            part.set_payload(Path(json_path).read_bytes())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment; filename=combined_report.json")
            msg.attach(part)

        # Send
        with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port) as server:
            server.starttls()
            server.login(email_config.sender_email, email_config.sender_password)
            server.send_message(msg)

        log.info(f"Email sent to {email_config.admin_emails}")
        return True

    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False
