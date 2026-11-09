"""Explicit Phase 2 settings loaded from TOML; no AWS prices are embedded in code."""
from dataclasses import dataclass
import math
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class CloudConfig:
    region: str
    cost_usd_per_hour_by_instance_type: dict[str, float]
    node_type_label: str = "pac.io/node-type"
    security_label: str = "pac.io/security-level"
    instance_type_label: str = "node.kubernetes.io/instance-type"
    zone_label: str = "topology.kubernetes.io/zone"
    metrics_max_age_seconds: int = 60
    opa_url: str = "http://localhost:8181"

    def __post_init__(self) -> None:
        if not self.region.strip():
            raise ValueError("Cloud region must be configured")
        if any(not name or not math.isfinite(value) or value < 0
               for name, value in self.cost_usd_per_hour_by_instance_type.items()):
            raise ValueError("Instance cost entries require a name and non-negative USD/hour estimate")
        if self.metrics_max_age_seconds <= 0:
            raise ValueError("metrics_max_age_seconds must be positive")

    @classmethod
    def from_toml(cls, path: str | Path) -> "CloudConfig":
        with Path(path).open("rb") as source:
            config = tomllib.load(source)
        aws = config.get("aws", {})
        labels = config.get("labels", {})
        metrics = config.get("metrics", {})
        opa = config.get("opa", {})
        costs = config.get("cost_usd_per_hour", {})
        return cls(
            region=aws.get("region", ""),
            cost_usd_per_hour_by_instance_type={str(k): float(v) for k, v in costs.items()},
            node_type_label=labels.get("node_type", "pac.io/node-type"),
            security_label=labels.get("security", "pac.io/security-level"),
            instance_type_label=labels.get("instance_type", "node.kubernetes.io/instance-type"),
            zone_label=labels.get("zone", "topology.kubernetes.io/zone"),
            metrics_max_age_seconds=int(metrics.get("max_age_seconds", 60)),
            opa_url=opa.get("url", "http://localhost:8181"),
        )
