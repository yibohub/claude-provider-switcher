"""CC Switch Lite 全局配置"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 代理配置
PROXY_TIMEOUT = 30
PROXY_MAX_PROVIDERS = 3
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_RECOVERY_INTERVAL = 60
PROXY_DEFAULT_STATE = False

# 健康检测配置
HEALTH_CHECK_INTERVAL = 60
HEALTH_DEGRADED_THRESHOLD = 2000
HEALTH_TIMEOUT = 5
HEALTH_LOG_RETENTION = 86400

# 代理数据文件
PROXY_STATE_FILE = DATA_DIR / "proxy_state.json"
PROXY_CONFIG_FILE = DATA_DIR / "config.json"

# 健康检测数据文件
HEALTH_LOG_FILE = DATA_DIR / "health_log.json"