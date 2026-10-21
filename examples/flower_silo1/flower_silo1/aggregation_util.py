"""Sample-weighted ArrayRecord aggregation for audit checks."""

from __future__ import annotations

from flwr.app import ArrayRecord, Message

from flower_silo1.task import arrays_to_vector, vector_to_arrays


def weighted_aggregate_train(
    replies: list[Message],
) -> tuple[ArrayRecord, int]:
    """FedAvg-style weighted mean over client ArrayRecords using num-examples."""
    total_examples = 0
    weighted: list[float] | None = None
    for msg in replies:
        metrics = msg.content.get("metrics")
        if metrics is None:
            raise ValueError("reply missing metrics")
        n = int(metrics.get("num-examples", 0))
        if n < 1:
            raise ValueError("num-examples must be >= 1")
        arrays = msg.content.get("arrays")
        if arrays is None:
            raise ValueError("reply missing arrays")
        vector = arrays_to_vector(arrays.to_numpy_ndarrays())
        if weighted is None:
            weighted = [0.0] * len(vector)
        if len(vector) != len(weighted):
            raise ValueError("parameter dimension mismatch across clients")
        for i, value in enumerate(vector):
            weighted[i] += float(value) * n
        total_examples += n
    if weighted is None or total_examples < 1:
        raise ValueError("no examples to aggregate")
    mean = [v / total_examples for v in weighted]
    return ArrayRecord(vector_to_arrays(mean)), total_examples
