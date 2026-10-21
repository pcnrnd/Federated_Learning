"""Flower ClientApp: local NumPy ridge on read-only Silo1 rows."""

from __future__ import annotations

import json

from flwr.app import ArrayRecord, Context, Message, MetricRecord, RecordDict
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


def _training_data(context: Context) -> tuple[list[list[float]], list[float], int]:
    """Load Silo1 rows once per process and build the local design matrix."""
    global _DATA_CACHE  # noqa: PLW0603
    if _DATA_CACHE is None:
        rows, manifest = load_rows_and_manifest()
        features, target = resolve_feature_target(
            rows,
            manifest,
            run_feature_columns=list(context.run_config.get("feature-columns") or []),
            run_target_column=str(context.run_config.get("target-column") or ""),
        )
        xs, ys, seen = matrix_from_rows(rows, features, target)
        _DATA_CACHE = {"xs": xs, "ys": ys, "seen": seen, "features": features, "target": target}
    cached = _DATA_CACHE
    return cached["xs"], cached["ys"], int(cached["seen"])  # type: ignore[index]


def _log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True))


@app.train()
def train(msg: Message, context: Context) -> Message:
    """Train from the global ArrayRecord on local Silo1 data."""
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
    local_arrays = vector_to_arrays(updated)
    local_record = ArrayRecord(local_arrays)
    local_hash = hash_array_record(local_record)
    config = msg.content.get("config")
    round_id = config.get("server-round", "?") if config is not None else "?"
    _log(
        "client_round_train",
        round=round_id,
        received_hash=received_hash,
        global_hash=received_hash,
        local_hash=local_hash,
        num_examples=num_examples,
        rows_seen=rows_seen,
        loss=loss,
        node_id=context.node_id,
    )
    metric_record = MetricRecord({"loss": loss, "num-examples": num_examples})
    content = RecordDict({"arrays": local_record, "metrics": metric_record})
    return Message(content=content, reply_to=msg)
