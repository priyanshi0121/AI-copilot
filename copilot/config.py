"""Central configuration, loaded from environment / .env."""
import os

from dotenv import load_dotenv

load_dotenv()


def _str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    def __init__(self):
        # URLs — defaults match host-run mode; docker-compose overrides for in-network
        self.prometheus_url = _str("PROMETHEUS_URL", "http://localhost:9090")
        self.order_service_url = _str("ORDER_SERVICE_URL", "http://localhost:5001")
        self.payment_service_url = _str("PAYMENT_SERVICE_URL", "http://localhost:5002")

        # detection
        self.check_interval_s = _int("CHECK_INTERVAL_S", 10)
        self.latency_threshold_s = _float("LATENCY_THRESHOLD_S", 0.5)
        self.error_rate_threshold = _float("ERROR_RATE_THRESHOLD", 0.3)
        self.resolve_after_checks = _int("RESOLVE_AFTER_CHECKS", 2)

        # correlation
        self.deploy_window_min = _int("DEPLOY_WINDOW_MIN", 30)

        # AI provider: anthropic | zai | openai | ollama
        self.ai_provider = _str("AI_PROVIDER", "anthropic").lower()
        self.anthropic_api_key = _str("ANTHROPIC_API_KEY", "")
        self.anthropic_model = _str("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.zai_api_key = _str("ZAI_API_KEY", "")
        self.zai_base_url = _str("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
        self.zai_model = _str("ZAI_MODEL", "glm-4.6")
        self.openai_api_key = _str("OPENAI_API_KEY", "")
        self.openai_model = _str("OPENAI_MODEL", "gpt-4o-mini")
        self.ollama_base_url = _str("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.ollama_model = _str("OLLAMA_MODEL", "llama3.2:3b")

        # cost model (documented assumptions)
        self.vcpu_hour_rate = _float("VCPU_HOUR_RATE", 0.0446)
        self.cpu_per_replica = _float("CPU_PER_REPLICA", 0.5)
        self.replicas = _int("REPLICAS", 1)
        self.baseline_latency_s = _float("BASELINE_LATENCY_S", 0.2)
        self.avg_order_value = _float("AVG_ORDER_VALUE", 42.0)

        # prioritization
        self.engineer_window_min = _int("ENGINEER_WINDOW_MIN", 60)
        self.est_fix_minutes = {"latency": 15, "error": 30, "down": 10}

        # data
        self.data_dir = _str("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))


config = Config()
