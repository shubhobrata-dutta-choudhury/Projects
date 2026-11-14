import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Deque, Dict, List, Optional

@dataclass
class TelemetryEvent:
    request_id: str
    timestamp: float
    tenant_id: str
    requested_model: str
    routed_model: str
    provider: str
    routing_strategy: str
    status: str
    fallback_triggered: bool
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    upstream_latency_ms: float
    total_gateway_latency_ms: float
    input_guardrail_latency_ms: float
    output_verification_latency_ms: float
    pii_redacted_count: int
    injection_risk_score: float
    injection_blocked: bool
    groundedness_score: float
    hallucination_flagged: bool
    selection_reason: str = ""

class TelemetryCollector:
    def __init__(self, db_path: Optional[str] = None, max_memory_events: int = 1000):
        if db_path is None:
            # Explicitly target project root data/ folder
            root_dir = Path(__file__).resolve().parent.parent.parent
            data_dir = root_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(data_dir / "telemetry.db")
        else:
            self.db_path = db_path
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._events: Deque[TelemetryEvent] = deque(maxlen=max_memory_events)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS request_telemetry (
                    request_id TEXT PRIMARY KEY,
                    timestamp REAL,
                    tenant_id TEXT,
                    requested_model TEXT,
                    routed_model TEXT,
                    provider TEXT,
                    routing_strategy TEXT,
                    status TEXT,
                    fallback_triggered INTEGER,
                    attempts INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    cost_usd REAL,
                    upstream_latency_ms REAL,
                    total_gateway_latency_ms REAL,
                    input_guardrail_latency_ms REAL,
                    output_verification_latency_ms REAL,
                    pii_redacted_count INTEGER,
                    injection_risk_score REAL,
                    injection_blocked INTEGER,
                    groundedness_score REAL,
                    hallucination_flagged INTEGER,
                    selection_reason TEXT,
                    p99_snapshot TEXT
                )
                """
            )
            conn.commit()

    def record_event(self, event: TelemetryEvent, p99_snapshot: Optional[Dict[str, float]] = None):
        with self._lock:
            self._events.append(event)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO request_telemetry VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        event.request_id,
                        event.timestamp,
                        event.tenant_id,
                        event.requested_model,
                        event.routed_model,
                        event.provider,
                        event.routing_strategy,
                        event.status,
                        1 if event.fallback_triggered else 0,
                        event.attempts,
                        event.prompt_tokens,
                        event.completion_tokens,
                        event.total_tokens,
                        event.cost_usd,
                        event.upstream_latency_ms,
                        event.total_gateway_latency_ms,
                        event.input_guardrail_latency_ms,
                        event.output_verification_latency_ms,
                        event.pii_redacted_count,
                        event.injection_risk_score,
                        1 if event.injection_blocked else 0,
                        event.groundedness_score,
                        1 if event.hallucination_flagged else 0,
                        event.selection_reason,
                        json.dumps(p99_snapshot or {}),
                    ),
                )
                conn.commit()

    def get_dashboard_summary(self) -> Dict[str, Any]:
        with self._lock:
            events = list(self._events)

        if not events:
            # Fallback to DB query if in-memory queue is empty
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM request_telemetry ORDER BY timestamp DESC LIMIT 100")
                    rows = cursor.fetchall()
                    if rows:
                        total_req = len(rows)
                        total_tokens = sum(r["total_tokens"] for r in rows)
                        total_cost = sum(r["cost_usd"] for r in rows)
                        pii_total = sum(r["pii_redacted_count"] for r in rows)
                        injections = sum(1 for r in rows if r["injection_blocked"])
                        fallbacks = sum(1 for r in rows if r["fallback_triggered"])
                        avg_groundedness = (
                            sum(r["groundedness_score"] for r in rows) / total_req if total_req else 1.0
                        )
                        return {
                            "total_requests": total_req,
                            "total_tokens": total_tokens,
                            "total_cost_usd": round(total_cost, 6),
                            "pii_redactions_total": pii_total,
                            "injections_blocked_total": injections,
                            "avg_groundedness_score": round(avg_groundedness, 4),
                            "fallback_rate": round(fallbacks / float(total_req), 4) if total_req else 0.0,
                            "recent_events": [dict(r) for r in rows[:10]],
                        }
            except Exception:
                pass

            return {
                "total_requests": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "pii_redactions_total": 0,
                "injections_blocked_total": 0,
                "avg_groundedness_score": 1.0,
                "fallback_rate": 0.0,
                "recent_events": [],
            }

        total_req = len(events)
        total_tokens = sum(e.total_tokens for e in events)
        total_cost = sum(e.cost_usd for e in events)
        pii_total = sum(e.pii_redacted_count for e in events)
        injections = sum(1 for e in events if e.injection_blocked)
        fallbacks = sum(1 for e in events if e.fallback_triggered)
        avg_groundedness = sum(e.groundedness_score for e in events) / total_req if total_req else 1.0

        return {
            "total_requests": total_req,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "pii_redactions_total": pii_total,
            "injections_blocked_total": injections,
            "avg_groundedness_score": round(avg_groundedness, 4),
            "fallback_rate": round(fallbacks / float(total_req), 4) if total_req else 0.0,
            "recent_events": [asdict(e) for e in list(events)[-10:]],
        }
