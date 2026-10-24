"""Flower ClientApp: local NumPy ridge on read-only silo rows."""

from __future__ import annotations

import json
import os

from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp

from flower_silo1.data import load_rows_and_manifest, matrix_from_rows, resolve_feature_target
from flower_silo1.task import (
    arrays_to_vector,
    hash_array_record,
    train_local_ridge,
    vector_to_arrays,
)

app = ClientApp()

_DATA_CACHE: dict[str, object] | None = None


def _silo_id(context: Context) -> str:
    """Resolve silo id from run config or container env."""
    cfg = context.run_config.get("silo-id")
    if cfg is not None and str(cfg).strip():
        return str(cfg).strip()
    env_id = os.environ.get("SILO_ID")
    if env_id:
        return env_id.strip()
    return "1"


def _training_data(context: Context) -> tuple[list[list[float]], list[float], int]:
    """Load silo rows once per process and build the local design matrix."""
    global _DATA_CACHE  # noqa: PLW0603
    if _DATA_CACHE is None:
        rows, manifest = load_rows_and_manifest()
        features, target = resolve_feature_target(
            rows,
            manifest,
            run_feature_columns=context.run_config["feature-columns"],
            run_target_column=context.run_config["target-column"],
        )
        xs, ys, seen = matrix_from_rows(rows, features, target)
        _DATA_CACHE = {"xs": xs, "ys": ys, "seen": seen}
    cached = _DATA_CACHE
    return cached["xs"], cached["ys"], int(cached["seen"])  # type: ignore[index]


def _log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True))


@app.train()
def train(msg: Message, context: Context) -> Message:
    """Train from the global ArrayRecord on local silo data."""
    received = msg.content["arrays"]
    received_hash = hash_array_record(received)
    global_vector = arrays_to_vector(received.to_numpy_ndarrays())
    xs, ys, rows_seen = _training_data(context)
    num_examples = len(xs)
    updated, loss = train_local_ridge(
        global_vector,
        xs,
        ys,
        step_size=float(context.run_config["step-size"]),
        l2=float(context.run_config["l2"]),
        steps=int(context.run_config["local-steps"]),
    )
    local_record = ArrayRecord(vector_to_arrays(updated))
    local_hash = hash_array_record(local_record)
    inbound = msg.content.get("config")
    round_id = inbound.get("server-round", "?") if inbound is not None else "?"
    silo_id = _silo_id(context)
    _log(
        "client_round_train",
        round=round_id,
        silo_id=silo_id,
        received_hash=received_hash,
        global_hash=received_hash,
        local_hash=local_hash,
        num_examples=num_examples,
        rows_seen=rows_seen,
        loss=loss,
        node_id=context.node_id,
    )
    metric_record = MetricRecord({"loss": loss, "num-examples": num_examples})
    config_record = ConfigRecord(
        {
            "silo-id": silo_id,
            "received-hash": received_hash,
            "local-hash": local_hash,
        }
    )
    content = RecordDict(
        {"arrays": local_record, "metrics": metric_record, "config": config_record}
    )
    return Message(content=content, reply_to=msg)
