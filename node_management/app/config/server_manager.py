"""서버 설정 파일 관리"""
from .settings import SERVERS_FILE
import yaml
from fastapi import HTTPException


def load_servers():
    """서버 설정 로드"""
    if SERVERS_FILE.exists():
        try:
            with open(SERVERS_FILE, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                # YAML이 None을 반환할 수 있음
                return data if data is not None else {}
        except (yaml.YAMLError, IOError) as e:
            print(f"서버 설정 파일 로드 오류: {e}")
            # 기본값 반환
            default = {
                "main": {
                    "base_url": "unix://var/run/docker.sock",
                    "label": "중앙 서버",
                    "type": "local",
                    "role": "central"
                }
            }
            save_servers(default)
            return default
    else:
        # 기본값 생성
        default = {
            "main": {
                "base_url": "unix://var/run/docker.sock",
                "label": "중앙 서버",
                "type": "local",
                "role": "central"
            }
        }
        save_servers(default)
        return default


def save_servers(servers: dict):
    """서버 설정 저장"""
    try:
        with open(SERVERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(servers, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except IOError as e:
        print(f"서버 설정 파일 저장 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 설정 저장 실패: {e}")

