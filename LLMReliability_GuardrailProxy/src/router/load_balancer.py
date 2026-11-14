from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from src.config import ModelEndpointConfig, ProxyConfig
from src.router.circuit_breaker import CircuitBreakerManager
from src.router.latency_tracker import SlidingWindowLatencyTracker
from src.router.rate_limit_tracker import RateLimitTracker

@dataclass
class CandidateSelection:
    model_config: ModelEndpointConfig
    reason: str
    p99_snapshot: Dict[str, float]

class AdaptiveLoadBalancer:
    """
    Real-Time P99 & Rate-Limit Aware Load Balancer.
    Evaluates:
    1. Circuit Breaker state (skips OPEN circuits)
    2. Rate-limit & Cooldown status (skips HTTP 429 throttled or >95% RPM/TPM saturated models)
    3. Sliding-window P99 latency vs SLA target (`sla_aware_p99`, `cost_optimal`, `weighted_round_robin`)
    """
    def __init__(self, config: ProxyConfig):
        self.config = config
        self.models: Dict[str, ModelEndpointConfig] = {m.id: m for m in config.models}
        self.latency_tracker = SlidingWindowLatencyTracker(
            window_seconds=config.gateway.latency_window_seconds
        )
        self.rate_limiter = RateLimitTracker(window_seconds=60)
        self.circuit_breaker = CircuitBreakerManager(
            failure_threshold=3, recovery_timeout_sec=12.0
        )
        self._rr_counter = 0
        for m in config.models:
            self.latency_tracker.register_model(m.id, default_latency_ms=m.base_latency_ms)
            self.rate_limiter.register_model(m.id, rpm_limit=m.rpm_limit, tpm_limit=m.tpm_limit)
            self.circuit_breaker.register_model(m.id)

    def select_order_of_candidates(
        self,
        requested_model: str = "auto",
        strategy: Optional[str] = None,
        sla_max_latency_ms: Optional[float] = None,
        estimated_tokens: int = 250,
        exclude_models: Optional[Set[str]] = None,
    ) -> List[CandidateSelection]:
        excluded = exclude_models or set()
        active_strategy = strategy or self.config.gateway.default_routing_strategy
        global_sla = sla_max_latency_ms or self.config.gateway.global_sla_p99_ms
        all_stats = self.latency_tracker.get_all_stats()
        p99_snapshot = {m_id: st.p99_ms for m_id, st in all_stats.items()}
        healthy_within_sla: List[tuple[float, ModelEndpointConfig, str]] = []
        degraded_candidates: List[tuple[float, ModelEndpointConfig, str]] = []
        for m_id, m_cfg in self.models.items():
            if m_id in excluded:
                continue
            cb_info = self.circuit_breaker.get_info(m_id)
            if cb_info.state == "OPEN":
                continue
            rl_status = self.rate_limiter.get_status(m_id, estimated_new_tokens=estimated_tokens)
            if rl_status.is_throttled:
                continue
            stats = all_stats.get(m_id)
            current_p99 = stats.p99_ms if stats else m_cfg.base_latency_ms * 1.25
            effective_sla = min(m_cfg.sla_p99_target_ms, global_sla)
            sla_ok = current_p99 <= effective_sla and rl_status.utilization_ratio < 0.92
            # Compute composite routing score (lower is better)
            if active_strategy == "cost_optimal":
                cost_per_1k = m_cfg.cost_per_1k_prompt_tokens + m_cfg.cost_per_1k_completion_tokens
                score = cost_per_1k * 1000.0 + (current_p99 * 0.05)
                reason = f"Cost-optimal selection (P99={current_p99:.0f}ms, SLA<={effective_sla:.0f}ms)"
            elif active_strategy == "weighted_round_robin":
                self._rr_counter += 1
                score = float((self._rr_counter % max(1, m_cfg.weight)))
                reason = f"Weighted round-robin (weight={m_cfg.weight}, P99={current_p99:.0f}ms)"
            else:
                # sla_aware_p99: prioritize flagship quality while keeping P99 well below SLA
                headroom_penalty = (current_p99 / max(1.0, effective_sla)) * 100.0
                utilization_penalty = rl_status.utilization_ratio * 40.0
                quality_bonus = m_cfg.quality_score * 55.0
                priority_penalty = (m_cfg.priority - 1) * 18.0
                score = headroom_penalty + utilization_penalty + priority_penalty - quality_bonus
                reason = (
                    f"SLA-aware P99 route (P99={current_p99:.0f}ms <= SLA {effective_sla:.0f}ms, "
                    f"RL={rl_status.utilization_ratio * 100:.0f}%)"
                )
            if requested_model != "auto" and m_id == requested_model:
                if sla_ok:
                    score -= 500.0
                    reason = f"Explicit model '{m_id}' healthy (P99={current_p99:.0f}ms)"
                else:
                    reason = f"Explicit model '{m_id}' breached SLA (P99={current_p99:.0f}ms > {effective_sla:.0f}ms)"
            if sla_ok:
                healthy_within_sla.append((score, m_cfg, reason))
            else:
                degraded_reason = (
                    f"Fallback candidate (P99={current_p99:.0f}ms vs SLA {effective_sla:.0f}ms)"
                )
                degraded_candidates.append((current_p99, m_cfg, degraded_reason))
        healthy_within_sla.sort(key=lambda x: x[0])
        degraded_candidates.sort(key=lambda x: x[0])
        ordered: List[CandidateSelection] = [
            CandidateSelection(model_config=cfg, reason=rsn, p99_snapshot=p99_snapshot)
            for _, cfg, rsn in healthy_within_sla
        ] + [
            CandidateSelection(model_config=cfg, reason=rsn, p99_snapshot=p99_snapshot)
            for _, cfg, rsn in degraded_candidates
        ]
        # Last-resort emergency fallback if all models were throttled/open
        if not ordered:
            fallback_cfg = min(self.models.values(), key=lambda m: m.base_latency_ms)
            ordered.append(
                CandidateSelection(
                    model_config=fallback_cfg,
                    reason="Emergency last-resort fallback (all endpoints saturated/open)",
                    p99_snapshot=p99_snapshot,
                )
            )
        return ordered

    def get_cluster_state(self) -> List[Dict]:
        cluster_info = []
        for m_id, m_cfg in self.models.items():
            lat = self.latency_tracker.get_stats(m_id)
            rl = self.rate_limiter.get_status(m_id)
            cb = self.circuit_breaker.get_info(m_id)
            sla_breached = lat.p99_ms > m_cfg.sla_p99_target_ms
            cluster_info.append(
                {
                    "id": m_id,
                    "provider": m_cfg.provider,
                    "tier": m_cfg.tier,
                    "priority": m_cfg.priority,
                    "sla_p99_target_ms": m_cfg.sla_p99_target_ms,
                    "sla_breached": sla_breached,
                    "latency": {
                        "sample_count": lat.count,
                        "p50_ms": lat.p50_ms,
                        "p95_ms": lat.p95_ms,
                        "p99_ms": lat.p99_ms,
                        "mean_ms": lat.mean_ms,
                    },
                    "rate_limit": {
                        "rpm_used": rl.rpm_used,
                        "rpm_limit": rl.rpm_limit,
                        "tpm_used": rl.tpm_used,
                        "tpm_limit": rl.tpm_limit,
                        "utilization_ratio": rl.utilization_ratio,
                        "is_throttled": rl.is_throttled,
                        "cooldown_remaining_sec": rl.cooldown_remaining_sec,
                    },
                    "circuit_breaker": {
                        "state": cb.state,
                        "consecutive_failures": cb.consecutive_failures,
                        "recovery_in_sec": cb.recovery_in_sec,
                    },
                    "pricing": {
                        "prompt_per_1k": m_cfg.cost_per_1k_prompt_tokens,
                        "completion_per_1k": m_cfg.cost_per_1k_completion_tokens,
                    },
                }
            )
        return cluster_info
