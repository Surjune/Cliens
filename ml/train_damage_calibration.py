"""Trains the damage calibration regressor and writes a versioned artifact.

Maps resistance-weighted stress onto an expected damage ratio, which is what turns
a dimensionless engineering quantity into the insurability judgement the product
reports.

A random forest is used rather than a smooth parametric fit for one reason that
matters downstream: the spread of its individual trees' predictions gives a
per-prediction uncertainty estimate, and the brief requires every model output to
carry a confidence indicator.

    node scripts/py.mjs ../ml/train_damage_calibration.py
"""

from __future__ import annotations

import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from common import (
    MODELS_DIR,
    artifact_name,
    constants,
    evaluate,
    write_metrics_report,
)
from generate_synthetic_data import FEATURE_COLUMNS, TARGET_COLUMN, generate

MODEL_NAME = "damage_calibration"


def main() -> int:
    """Train, evaluate and persist the damage calibration model."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    frame = generate()
    features = frame[FEATURE_COLUMNS]
    target = frame[TARGET_COLUMN]

    # Fit on a plain array rather than a DataFrame. An estimator fitted with
    # feature names warns on every prediction made from an array, and inference
    # builds arrays deliberately — constructing a DataFrame per request would cost
    # more than it buys. FEATURE_COLUMNS remains the contract, stored alongside.
    features_train, features_test, target_train, target_test = train_test_split(
        features.to_numpy(),
        target.to_numpy(),
        test_size=constants.TRAIN_TEST_SPLIT_FRACTION,
        random_state=constants.RANDOM_SEED,
    )

    model = RandomForestRegressor(
        n_estimators=constants.DAMAGE_MODEL_N_ESTIMATORS,
        max_depth=constants.DAMAGE_MODEL_MAX_DEPTH,
        min_samples_leaf=constants.DAMAGE_MODEL_MIN_SAMPLES_LEAF,
        random_state=constants.RANDOM_SEED,
        n_jobs=-1,
    )
    model.fit(features_train, target_train)

    metrics = evaluate(
        model.predict(features_test),
        target_test,
        units="damage ratio, 0-1",
        n_train=len(features_train),
    )

    artifact = MODELS_DIR / artifact_name(MODEL_NAME)
    joblib.dump(
        {
            "model": model,
            "feature_columns": FEATURE_COLUMNS,
            "sklearn_version": __import__("sklearn").__version__,
        },
        artifact,
    )

    report = write_metrics_report(
        MODEL_NAME,
        artifact,
        metrics,
        extra={
            "training_data": "synthetic",
            "honesty_note": (
                "Trained on synthetic data generated from the vulnerability curve in "
                "core/constants.py. A high R2 shows the model recovered that curve; it "
                "is NOT evidence the curve describes real buildings. Not validated "
                "against observed Indian damage data."
            ),
            "feature_importances": dict(
                zip(FEATURE_COLUMNS, (float(v) for v in model.feature_importances_), strict=True)
            ),
        },
    )

    print(f"Trained {MODEL_NAME}")
    print(metrics.render())
    print(f"  artifact  {artifact.name}")
    print(f"  report    {report.name}")
    print(
        "\n  NOTE: synthetic training data. These metrics measure curve recovery,\n"
        "  not real-world accuracy. See ml/generate_synthetic_data.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
