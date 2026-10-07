"""
AutoSchema-Heal CLI & Live Demonstration Dashboard.

Provides an interactive visualization of autonomous schema drift remediation
with CEGIS formal verification and streaming throughput telemetry.
"""

from __future__ import annotations
import json
import time
from typing import Any, Dict
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.live import Live

from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.core.engine import AutoSchemaEngine
from autoschema_heal.synthesis.llm_client import MockLLMClient


console = Console(highlight=False)


PAYMENT_TARGET_SCHEMA = {
    "title": "CanonicalPaymentEvent",
    "type": "object",
    "properties": {
        "transaction_id": {"type": "string"},
        "customer_email": {"type": "string"},
        "amount_usd": {"type": "number"},
        "created_at": {"type": "string"}
    },
    "required": ["transaction_id", "customer_email", "amount_usd", "created_at"]
}


def run_live_demo():
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]AutoSchema-Heal: Autonomous Schema Drift Remediation[/bold cyan]\n"
            "[italic white]Program-Synthesized JQ Transformations with CEGIS Formal Verification[/italic white]",
            border_style="cyan"
        )
    )

    schema = TargetSchema(json_schema=PAYMENT_TARGET_SCHEMA)
    mock_client = MockLLMClient(simulate_cegis_round_failure=True)
    engine = AutoSchemaEngine(
        target_schema=schema,
        llm_client=mock_client,
        fuzzer_cases=12,
        retention_threshold=0.70,
    )

    console.print("\n[bold yellow]1. Canonical Target Contract Enforced:[/bold yellow]")
    console.print(
        Syntax(
            json.dumps(PAYMENT_TARGET_SCHEMA, indent=2),
            "json",
            theme="monokai",
            line_numbers=False
        )
    )

    console.print("\n[bold yellow]2. Simulating Baseline Streaming Ingestion...[/bold yellow]")
    canonical_event = {
        "transaction_id": "tx_leg_9901",
        "customer_email": "alice@bank.org",
        "amount_usd": 150.00,
        "created_at": "2026-10-06T12:00:00Z"
    }

    # Initial registration
    res0 = engine.ingest(canonical_event)
    console.print(f"  [green][OK][/green] Ingested canonical event | Fast Path: {res0.fast_path} | Latency: {res0.latency_microseconds:.1f} us")

    console.print("\n[bold red]3. SUDDEN UPSTREAM SCHEMA DRIFT DETECTED![/bold red]")
    drift_event = {
        "charge_id": "ch_v3_994821",
        "user": {
            "email": "drifted_customer@fintech.io"
        },
        "amount_cents": 2999,
        "timestamp_epoch": 1700000000
    }
    console.print(
        Syntax(
            json.dumps(drift_event, indent=2),
            "json",
            theme="monokai",
            line_numbers=False
        )
    )

    console.print("\n[bold cyan]4. Triggering CEGIS Autonomous Remediation Loop...[/bold cyan]")
    t0 = time.perf_counter()
    res_drift = engine.ingest(drift_event)
    elapsed = time.perf_counter() - t0

    if res_drift.drift_healed:
        console.print(f"  [bold green][SUCCESS][/bold green] Synthesized & Certified in {res_drift.cegis_rounds} CEGIS round(s) ({elapsed*1000:.1f} ms)!")
        cached_info = engine.cache.get(res_drift.fingerprint)
        if cached_info:
            console.print("\n[bold green]Verified Pure JQ Program Emitted:[/bold green]")
            console.print(Syntax(cached_info.jq_source.strip(), "jq", theme="monokai"))

        console.print("\n[bold green]Transformed Output (Conforms to Canonical Target Contract):[/bold green]")
        console.print(
            Syntax(
                json.dumps(res_drift.data, indent=2),
                "json",
                theme="monokai"
            )
        )
    else:
        console.print(f"  [bold red][FAILED][/bold red] Quarantined to DLQ: {res_drift.quarantine_reason}")

    console.print("\n[bold yellow]5. Streaming 10,000 Subsequent Events through Native C Fast Path...[/bold yellow]")
    batch_size = 10_000
    sub_t0 = time.perf_counter()
    for i in range(batch_size):
        drift_event["charge_id"] = f"ch_v3_{i}"
        r = engine.ingest(drift_event)
        assert r.fast_path is True

    sub_elapsed = time.perf_counter() - sub_t0
    rate = batch_size / sub_elapsed

    stats_table = Table(title="Pipeline Telemetry & Performance", border_style="cyan")
    stats_table.add_column("Metric", style="bold white")
    stats_table.add_column("Observed Value", style="yellow")

    stats = engine.stats()
    stats_table.add_row("Total Stream Records", f"{stats['total_processed']:,}")
    stats_table.add_row("Fast Path Cache Hits", f"{stats['fast_path_count']:,}")
    stats_table.add_row("Fast Path Ratio", f"{stats['fast_path_percentage']:.2f}%")
    stats_table.add_row("Streaming Throughput", f"{rate:,.0f} records/sec")
    stats_table.add_row("Average Fast Path Latency", f"{(sub_elapsed / batch_size) * 1_000_000:.2f} us / record")
    stats_table.add_row("DLQ Quarantined", f"{stats['quarantine_count']}")

    console.print()
    console.print(stats_table)
    console.print()


def main():
    run_live_demo()


if __name__ == "__main__":
    main()
