"""애플리케이션 설정 상수"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
_CONFIG_DIR_RAW = os.getenv("FED_CONFIG_DIR")
CONFIG_DIR = Path(_CONFIG_DIR_RAW).expanduser() if _CONFIG_DIR_RAW else BASE_DIR / "config"
if not CONFIG_DIR.is_absolute():
    CONFIG_DIR = (BASE_DIR / CONFIG_DIR).resolve()
CONFIG_DIR.mkdir(exist_ok=True)
SERVERS_FILE = CONFIG_DIR / "servers.yaml"

API_KEY = os.getenv("FED_API_KEY", "")
API_KEY_HEADER = "X-FED-API-Key"

