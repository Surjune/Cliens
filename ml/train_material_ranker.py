"""Trains the material ranking model and writes a versioned artifact.

WHERE THE LABELS COME FROM, stated up front because it determines what this model
is worth. There is no dataset of "which material a builder should have chosen".
Labels are therefore **derived by simulation**: for a sampled hazard profile and a
candidate material, the label is the damage reduction that material achieves
relative to an unresisting reference, computed with the same vulnerability curve
the damage model uses.

So this ranker is a fast learned surrogate of a deterministic calculation, not
independent evidence about materials. That is a real and deliberate limitation,
recorded in the README. What it buys is speed and smoothness: ranking every
candidate by re-running the full score engine would mean a combinatorial sweep on
every request, and the surrogate collapses that to one vectorised prediction.

Cost is deliberately **not** a model input. Ranking by damage-reduction-per-rupee
is a policy decision the service applies afterwards, so it can be changed or
explained without retraining.

    node scripts/py.mjs ../ml/train_material_ranker.py
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split

from common import MODELS_DIR, artifact_name, constants, evaluate, write_metrics_report
from generate_synthetic_data import vulnerability_curve

MODEL_NAME = "material_ranker"

# Positional order is part of the artifact's contract; see the note in
# generate_synthetic_data.FEATURE_COLUMNS.
FEATURE_COLUMNS = [
    "intensity_wind",
    "intensity_flood",
    "intensity_heat",
    "component_weight",
    "sensitivity_wind",
    "sensitivity_flood",
    "sensitivity_heat",
    "resistance_wind",
    "resistance_flood",
    "resistance_heat",
]
TARGET_COLUMN = "damage_reduction"


def build_dataset() -> pd.DataFrame:
    """Simulate (hazard profile, component, material) combinations and their benefit.

    For each sample the label is::

        damage(unresisted stress) - damage(stress with this material's resistance)

    holding everything else fixed. That isolates the contribution of the single
    material being considered, which is exactly the quantity a recommendation
    needs to rank on.
    """
    rng = np.random.default_rng(constants.RANDOM_SEED)
    rows: list[dict[str, float]] = []

    samples_per_component = constants.SYNTHETIC_TRAINING_SAMPLES // len(
        constants.BUILDING_COMPONENTS
    )

    for component in constants.BUILDING_COMPONENTS:
        weight = constants.COMPONENT_WEIGHTS[component]
        sensitivity = constants.COMPONENT_HAZARD_SENSITIVITY[component]

        intensities = rng.uniform(
            0.0, constants.MAX_NORMALISED_HAZARD_INTENSITY, size=(samples_per_component, 3)
        )
        # Resistances span the full unit interval so the model generalises beyond
        # the catalogue's current 14 entries to any material added later.
        resistances = rng.uniform(0.0, 1.0, size=(samples_per_component, 3))

        for intensity_row, resistance_row in zip(intensities, resistances, strict=True):
            per_hazard = dict(zip(constants.HAZARDS, intensity_row, strict=True))
            per_resistance = dict(zip(constants.HAZARDS, resistance_row, strict=True))

            unresisted = sum(
                weight * sensitivity[hazard] * per_hazard[hazard] for hazard in constants.HAZARDS
            )
            resisted = sum(
                weight
                * sensitivity[hazard]
                * per_hazard[hazard]
                * (1.0 - per_resistance[hazard])
                for hazard in constants.HAZARDS
            )

            reduction = float(
                vulnerability_curve(np.array([unresisted]))[0]
                - vulnerability_curve(np.array([resisted]))[0]
            )

            rows.append(
                {
                    "intensity_wind": per_hazard["wind"],
                    "intensity_flood": per_hazard["flood"],
                    "intensity_heat": per_hazard["heat"],
                    "component_weight": weight,
                    "sensitivity_wind": sensitivity["wind"],
                    "sensitivity_flood": sensitivity["flood"],
                    "sensitivity_heat": sensitivity["heat"],
                    "resistance_wind": per_resistance["wind"],
                    "resistance_flood": per_resistance["flood"],
                    "resistance_heat": per_resistance["heat"],
                    TARGET_COLUMN: reduction,
                }
            )

    return pd.DataFrame(rows)


def main() -> int:
    """Train, evaluate and persist the material ranking model."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    frame = build_dataset()
    features = frame[FEATURE_COLUMNS]
    target = frame[TARGET_COLUMN]

    # Fitted on an array, not a DataFrame — see the note in
    # train_damage_calibration.py.
    features_train, features_test, target_train, target_test = train_test_split(
        features.to_numpy(),
        target.to_numpy(),
        test_size=constants.TRAIN_TEST_SPLIT_FRACTION,
        random_state=constants.RANDOM_SEED,
    )

    model = GradientBoostingRegressor(
        n_estimators=constants.RANKER_MODEL_N_ESTIMATORS,
        max_depth=constants.RANKER_MODEL_MAX_DEPTH,
        random_state=constants.RANDOM_SEED,
    )
    model.fit(features_train, target_train)

    metrics = evaluate(
        model.predict(features_test),
        target_test,
        units="damage ratio reduction, 0-1",
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
            "training_data": "simulated",
            "honesty_note": (
                "Labels are derived by simulation from the same vulnerability curve the "
                "damage model uses, so this is a fast surrogate of a deterministic "
                "calculation rather than independent evidence about materials."
            ),
            "cost_handling": (
                "Cost is not a model input. Ranking by damage-reduction-per-cost is "
                "applied by the service afterwards so the policy can change without "
                "retraining."
            ),
        },
    )

    print(f"Trained {MODEL_NAME}")
    print(metrics.render())
    print(f"  artifact  {artifact.name}")
    print(f"  report    {report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
