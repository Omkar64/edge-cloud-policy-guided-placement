"""Adapters from Kubernetes node/metrics values to the Phase 1 node schema."""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from cloud.config import CloudConfig
from cloud.types import KubernetesNode, NodeMetrics

GIB = Decimal(1024 ** 3)
_CPU_SUFFIXES = {"": Decimal(1), "n": Decimal("0.000000001"), "u": Decimal("0.000001"), "m": Decimal("0.001")}
_MEMORY_SUFFIXES = {
    "": Decimal(1), "k": Decimal(1000), "K": Decimal(1000), "M": Decimal(1000**2),
    "G": Decimal(1000**3), "T": Decimal(1000**4), "P": Decimal(1000**5), "E": Decimal(1000**6),
    "Ki": Decimal(1024), "Mi": Decimal(1024**2), "Gi": Decimal(1024**3),
    "Ti": Decimal(1024**4), "Pi": Decimal(1024**5), "Ei": Decimal(1024**6),
}


class NodeAdaptationError(ValueError):
    """Kubernetes data cannot safely be translated into the placement schema."""


class MetricsUnavailableError(RuntimeError):
    """Required live metrics are absent; no synthetic values were substituted."""


def _quantity(value: str | int | float, suffixes: dict[str, Decimal], metric: str) -> Decimal:
    raw = str(value).strip()
    suffix = next((candidate for candidate in sorted(suffixes, key=len, reverse=True)
                   if candidate and raw.endswith(candidate)), "")
    number = raw[:-len(suffix)] if suffix else raw
    try:
        parsed = Decimal(number) * suffixes[suffix]
    except (InvalidOperation, KeyError) as exc:
        raise NodeAdaptationError(f"Invalid Kubernetes {metric} quantity: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise NodeAdaptationError(f"Kubernetes {metric} must be finite and non-negative: {value!r}")
    return parsed


def parse_cpu_quantity(value: str | int | float) -> Decimal:
    """Convert Kubernetes CPU quantities (cores, m, u, n) into CPU cores."""
    return _quantity(value, _CPU_SUFFIXES, "CPU")


def parse_memory_quantity(value: str | int | float) -> Decimal:
    """Convert Kubernetes memory quantities into bytes."""
    return _quantity(value, _MEMORY_SUFFIXES, "memory")


class KubernetesNodeAdapter:
    def __init__(self, config: CloudConfig):
        self.config = config

    def adapt(self, node: KubernetesNode, metrics: NodeMetrics) -> dict:
        labels = node.labels
        required_labels = (self.config.node_type_label, self.config.security_label,
                           self.config.instance_type_label)
        missing = [key for key in required_labels if not labels.get(key)]
        if missing:
            raise NodeAdaptationError(f"Node {node.name!r} is missing required labels: {', '.join(missing)}")
        node_type, security = labels[self.config.node_type_label], labels[self.config.security_label]
        if node_type not in {"edge", "cloud"}:
            raise NodeAdaptationError(f"Node {node.name!r} has unsupported node type {node_type!r}")
        if security not in {"low", "medium", "high"}:
            raise NodeAdaptationError(f"Node {node.name!r} has unsupported security classification {security!r}")
        instance_type = labels[self.config.instance_type_label]
        if instance_type not in self.config.cost_usd_per_hour_by_instance_type:
            raise NodeAdaptationError(f"No configured USD/hour estimate for instance type {instance_type!r}")
        try:
            if not metrics.sampled_at:
                raise MetricsUnavailableError(f"Metrics timestamp is missing for node {node.name!r}")
            try:
                sampled_at = datetime.fromisoformat(metrics.sampled_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise MetricsUnavailableError(f"Metrics timestamp is invalid for node {node.name!r}: {metrics.sampled_at!r}") from exc
            if sampled_at.tzinfo is None:
                raise MetricsUnavailableError(f"Metrics timestamp must include a timezone for node {node.name!r}")
            age = (datetime.now(timezone.utc) - sampled_at.astimezone(timezone.utc)).total_seconds()
            if age > self.config.metrics_max_age_seconds:
                raise MetricsUnavailableError(f"Metrics are stale for node {node.name!r} ({age:.1f}s old)")
            cpu_capacity = parse_cpu_quantity(node.capacity["cpu"])
            memory_capacity_bytes = parse_memory_quantity(node.capacity["memory"])
            cpu_used = parse_cpu_quantity(metrics.cpu_usage)
            memory_used_bytes = parse_memory_quantity(metrics.memory_usage)
            latency = float(metrics.latency_ms)
        except KeyError as exc:
            raise NodeAdaptationError(f"Node {node.name!r} or its metrics lack required field {exc}") from exc
        if cpu_capacity <= 0 or memory_capacity_bytes <= 0:
            raise NodeAdaptationError(f"Node {node.name!r} must report positive CPU and memory capacity")
        if not 0 <= latency or latency != latency or latency == float("inf"):
            raise NodeAdaptationError(f"Node {node.name!r} latency must be finite and non-negative")
        cpu_percent = float(100 * cpu_used / cpu_capacity)
        memory_percent = float(100 * memory_used_bytes / memory_capacity_bytes)
        memory_capacity_gib = memory_capacity_bytes / GIB
        available_cpu = max(Decimal(0), cpu_capacity - cpu_used)
        available_memory = max(Decimal(0), memory_capacity_bytes - memory_used_bytes) / GIB
        return {
            "id": node.name,
            "type": node_type,
            "cpu_capacity": float(cpu_capacity),
            "memory_capacity": float(memory_capacity_gib),
            "cpu_utilization": cpu_percent,
            "memory_utilization": memory_percent,
            "latency": latency,
            "cost": self.config.cost_usd_per_hour_by_instance_type[instance_type],
            "security": security,
            "available_cpu": float(available_cpu),
            "available_memory": float(available_memory),
            "instance_type": instance_type,
            "availability_zone": labels.get(self.config.zone_label),
            "latency_source": metrics.latency_source,
            "metrics_sampled_at": metrics.sampled_at,
            "cost_unit": "usd_per_hour_estimate",
            "labels": dict(labels),
        }
