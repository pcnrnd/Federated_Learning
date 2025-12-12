1. 홈 디렉토리에 플러그인 폴더 생성 (없으면 만들고, 있으면 넘어감)
- $ mkdir -p ~/.docker/cli-plugins

2. 시스템에 있는 파일(원본)을 홈 폴더에 '바로가기'로 연결
- $ ln -s /usr/libexec/docker/cli-plugins/docker-compose ~/.docker/cli-plugins/docker-compose	

### docker compose file
- https://raw.githubusercontent.com/datahub-project/datahub/v1.3.0/docker/quickstart/docker-compose.quickstart-profile.yml

- .env 파일 생성 (버전 v1.3.0 지정)
"""cat <<EOF > .env
DATAHUB_VERSION=v1.3.0
UI_INGESTION_DEFAULT_CLI_VERSION=v1.3.0
datahub_actions_version=v0.0.15
EOF """

- $ docker compose -f compose.datahub.yaml --profile quickstart up -d