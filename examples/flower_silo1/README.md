# Flower Silo1 minimal deployment example (Flwr 1.41.0)

Real-network **ServerApp + ClientApp** with one SuperLink, one SuperNode, two FedAvg
rounds, NumPy ridge local training on read-only Silo1 `rows.json`.

## Layout

- `flower_silo1/server_app.py` — `Silo1FedAvg` (`min_train_nodes=1`, `fraction_evaluate=0`)
- `flower_silo1/client_app.py` — `@app.train()` with `Message` / `ArrayRecord` / `MetricRecord`
- `flower_silo1/data.py` — read-only volume paths and optional SHA-256 pin
- `docker/compose.yaml` — two services on an internal bridge, **no published host ports**

## Source checks (no Docker)

```powershell
cd examples/flower_silo1
python scripts/check_source.py
python -m compileall flower_silo1
```

Optional (requires `flwr==1.41.0` installed):

```powershell
pip install -e .
python -c "from flower_silo1.server_app import app as s; from flower_silo1.client_app import app as c"
```

## DTS PoC runner (`scripts/dts_poc_run.sh`)

Run only on DTS Linux (not Windows Docker). The script enforces: EXIT trap with
evidence capture then bounded `compose down`; DTS available memory ≥ 4.5 GiB before
build; pressure watch &lt; 3 GiB during build/run; `docker build --memory=1g`;
overall `timeout --kill-after=15 660s`; GET probes on `http://127.0.0.1:18080/api/training-rounds`
and `/api/models` via curl (connect 2s / max 5s, no masked failures).

```bash
bash ~/fed-flower-poc-20261021/app/scripts/dts_poc_run.sh
```

## Proposed runtime (manual compose)

1. Set `SILO1_TARGET_COLUMN` / `SILO1_FEATURE_COLUMNS` (or `tool.flwr.app.config`
   `feature-columns` / `target-column` / `parameter-dim`) from `manifest.json` on the volume.
2. Build and start isolated sidecars:

```powershell
cd examples/flower_silo1/docker
$env:FLWR_VERSION="1.41.0"
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d
```

3. Register SuperLink profile inside the SuperLink container and submit the run:

```powershell
docker compose -f compose.yaml exec superlink sh -c '
  mkdir -p ~/.flwr &&
  printf "%s\n" "[superlink.silo1]" "address = \"superlink:8000\"" "insecure = true" >> ~/.flwr/config.toml &&
  flwr run /app silo1 --stream
'
```

4. Inspect JSON log lines (`server_round_*`, `client_round_train`,
   `verify_round2_base_equals_round1_result`) and `artifacts/final_weights.npz` on the SuperLink container filesystem.

5. Tear down:

```powershell
docker compose -f compose.yaml down
```

## Silo1 data pin

Default relative path under `SILO1_DATA_ROOT`:

`fed-final-path603396-20261021/.cleaned/f27880259e7c004a83f7515ca6ad70a792ee7cba6d4897a28994c1689f69f939/rows.json`

Expected SHA-256: `8164fad0f8a29f18c677a99ad7e791b76e3c318dc15569d27bd2ea5432837356`

Override with `SILO1_ROWS_JSON` / `SILO1_ROWS_SHA256` if needed.
