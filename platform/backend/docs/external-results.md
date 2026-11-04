# Import completed results from external training engines

The new path imports `federated-result-v1` bundles without changing native ridge,
FedAvg or Flower job behavior. It does not call a training engine or execute a
model. The first profile accepts numeric NPZ weights and a TorchScript artifact;
the importer depends on NumPy, not deFAI, Torch or a particular Flower version.
The exact shared contract is in
[`docs/specs/2026-11-04-result-interchange.md`](../../../docs/specs/2026-11-04-result-interchange.md).

## Stage a trusted bundle

The server reads **operator-approved local files**, not arbitrary browser paths
or uploaded archives. Put a complete bundle directory under
`FED_EXTERNAL_RESULTS_DIR`, or the default `FED_CONFIG_DIR/external-results/inbox`.
For example, with `FED_CONFIG_DIR=/srv/config`, stage:

```text
/srv/config/external-results/inbox/experiment-001/
    result.json
    weights.npz
    model.ts
```

The request contains only the child directory's `bundle_id`. Its characters are
ASCII letters/digits, underscore or hyphen, starting with a letter/digit, at
most 128 characters. Paths outside the inbox are rejected.

## Inspect, import and read

All routes inherit the normal `X-FED-API-Key` gate when `FED_API_KEY` is configured.
Use that header with the following requests where appropriate:

```sh
curl -X POST http://localhost:8010/api/external-results/inspect \
  -H 'Content-Type: application/json' \
  -d '{"bundle_id":"experiment-001"}'

curl -X POST http://localhost:8010/api/external-results/import \
  -H 'Content-Type: application/json' \
  -d '{"bundle_id":"experiment-001","name":"external-model","version":"1.0.0"}'

curl 'http://localhost:8010/api/external-results?name=external-model&version=1.0.0'
```

Inspect validates the format version, history/metric definitions, numeric array
headers/shapes/dtypes/values, bounded sizes, paths and file hashes. It returns the
manifest plus `artifact_integrity_verified=true`, `inference_verified=false`.

Import copies the verified bundle to the platform's model artifact store,
revalidates the copy, and registers its inference file through the existing model
registry. The original result remains retrievable and its metric units are not
converted. An external result never goes through the platform's FedAvg aggregate
verification. Source files may be removed after a successful import.

The first import returns 201 and the existing `ModelEntry` schema. Repeating the
same name/version/bundle returns the same entry with 200. Reusing a model version
for a different result returns 409. Invalid input returns 422; damaged stored
results return 409. Registry metadata records the bundle identity and origin.
The existing model list also shows the imported model, but this change adds no
dedicated upload screen or automatic chart ingestion.

## Prediction and trust boundary

The inference file is opaque during import: no TorchScript execution occurs in
the management backend. Hash validation is integrity checking, not authenticity
or a sandbox. Only trusted producer/operator-approved artifacts should be staged.
Successful import does not certify the model's behavior or mark it prediction-
verified. Use normal packaging, health, prediction, and deployment checks next.
For deFAI's exported TorchScript models, the inference image needs the documented
PyTorch runtime (currently `torch>=2.6,<2.7`) through `extra_requirements`, and
inputs must follow the exported preprocessing/schema.

This phase does not add remote execution control, full optimizer/client resume,
vertical message transport, clinical validation, or a shared Python environment.
