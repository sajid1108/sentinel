"""Model artifacts: save, register and load with verification (§6.4, §13.3, §14.1).

backend/artifacts/models/{return,abuse}.joblib and backend/artifacts/model_registry.json are committed.
load_bundle() checks the file's SHA-256 against the registry before unpickling, then the bundle's
sklearn version against the running one. Any mismatch raises ArtifactError; there is no fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import sklearn

from sentinel.settings import ARTIFACTS_DIR

MODEL_NAMES = ("return", "abuse")
REGISTRY_FILE = "model_registry.json"
MODEL_VERSION_PREFIX = "hgb-fs1.0"


class ArtifactError(RuntimeError):
    """A model artifact is missing, altered, unregistered or built with another sklearn version."""


def artifact_path(name: str, artifacts_dir: Path = ARTIFACTS_DIR) -> Path:
    return Path(artifacts_dir) / "models" / f"{name}.joblib"


def registry_path(artifacts_dir: Path = ARTIFACTS_DIR) -> Path:
    return Path(artifacts_dir) / REGISTRY_FILE


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_version(name: str, sha256: str) -> str:
    return f"{name}-{MODEL_VERSION_PREFIX}-{sha256[:8]}"


def existing_artifacts(artifacts_dir: Path = ARTIFACTS_DIR) -> list[Path]:
    paths = [artifact_path(n, artifacts_dir) for n in MODEL_NAMES] + [registry_path(artifacts_dir)]
    return [p for p in paths if p.exists()]


def save_bundles(bundles: dict[str, dict], artifacts_dir: Path = ARTIFACTS_DIR, force: bool = False) -> dict:
    """Write both bundles and the registry. Refuses to overwrite anything unless force=True."""
    existing = existing_artifacts(artifacts_dir)
    if existing and not force:
        raise ArtifactError("artifacts already exist (" + ", ".join(str(p) for p in existing)
                            + "); pass --force to overwrite")
    models = {}
    for name in MODEL_NAMES:
        bundle = bundles[name]
        path = artifact_path(name, artifacts_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, path)
        sha = sha256_file(path)
        models[name] = {
            "model_version": model_version(name, sha),
            "artifact": path.relative_to(artifacts_dir).as_posix(),
            "sha256": sha,
            "feature_set_version": bundle["feature_set_version"],
            "sklearn_version": bundle["sklearn_version"],
            "calibration_method": bundle["calibration_method"],
            "feature_list": bundle["feature_list"],
            "monotonic_constraints": bundle.get("monotonic_constraints", {}),
            "train_window": bundle["train_window"],
            "calibration_window": bundle["calibration_window"],
            "trained_at": bundle["trained_at"],
        }
    # histogram gradient boosting sums gradients in parallel: hashes are comparable only on the same core count
    registry = {"models": models, "cpu_count": os.cpu_count()}
    registry_path(artifacts_dir).write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return registry


def load_registry(artifacts_dir: Path = ARTIFACTS_DIR) -> dict:
    path = registry_path(artifacts_dir)
    if not path.exists():
        raise ArtifactError(f"model registry not found at {path}; run `python -m sentinel.cli train`")
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(name: str, artifacts_dir: Path = ARTIFACTS_DIR) -> dict:
    """Verified load. The bundle gains "model_version" from the registry."""
    entry = load_registry(artifacts_dir).get("models", {}).get(name)
    if entry is None:
        raise ArtifactError(f"model {name!r} is not in the registry")
    path = Path(artifacts_dir) / entry["artifact"]
    if not path.exists():
        raise ArtifactError(f"artifact for model {name!r} not found at {path}")
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise ArtifactError(f"SHA-256 mismatch for {path}: registry {entry['sha256']}, file {actual}. "
                            "The artifact was altered or the registry is stale; refusing to load.")
    bundle = joblib.load(path)
    if bundle.get("sklearn_version") != sklearn.__version__:
        raise ArtifactError(f"model {name!r} was built with scikit-learn {bundle.get('sklearn_version')}, "
                            f"running {sklearn.__version__}; refusing to load. Install the pinned version.")
    if bundle.get("name") != name:
        raise ArtifactError(f"artifact at {path} holds model {bundle.get('name')!r}, not {name!r}")
    return {**bundle, "model_version": entry["model_version"], "sha256": actual}
