"""애플리케이션 설정 상수"""
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_DIR.mkdir(exist_ok=True)
SERVERS_FILE = CONFIG_DIR / "servers.yaml"

