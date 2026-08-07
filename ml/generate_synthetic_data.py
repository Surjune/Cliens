"""Documents and reproduces the synthetic training data, including every assumption.

READ THIS BEFORE TRUSTING ANY METRIC FROM THE MODELS TRAINED ON THIS DATA.

No public, machine-readable dataset pairs Indian building material specifications
with per-building post-cyclone damage ratios. Assembling one would mean digitising
individual post-event damage surveys, which is out of scope for v1. So the damage
calibration model is trained on **synthetic data generated from a vulnerability
curve we defined ourselves**, in ``core/constants.py``:

    damage = 1 - exp(-k * stress^alpha)

The honest consequence, stated plainly and repeated in the README: a high R² on
this data shows only that the model successfully recovered the curve it was shown.
**It is not evidence that the curve describes real buildings.** The curve's form is
standard in catastrophe modelling and its two anchor points are documented
judgements, but they have not been validated against observed Indian damage data.

What the model does buy, given that: a smooth, monotonic, uncertainty-aware
interpolator with a stable serialisation format and a retraining path. When real
damage data becomes available, ``train_damage_calibration.py`` can be pointed at it
without changing anything downstream.

Run directly to regenerate and inspect the dataset:

    node scripts/py.mjs ../ml/generate_synthetic_data.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import DATA_DIR, constants, new_rng

# Feature columns, in the exact order the models consume them. Order matters:
# scikit-learn estimators index features positionally, so a reordering here would
# silently mis-predict at inference time.
FEATURE_COLUMNS = [
    "stress_total",
    "stress_wind",
    "stress_flood",
    "stress_heat",
    "area_factor",
]
TARGET_COLUMN = "damage_ratio"


def vulnerability_curve(stress: np.ndarray) -> np.ndarray:
    """The noiseless damage ratio for a given resistance-weighted stress.

    The exponential form ``1 - exp(-k * s^alpha)`` is standard in catastrophe
    modelling: damage rises slowly at low load, accelerates through the design
    load, and saturates towards total loss. Coefficients are in ``constants``.
    """
    return 1.0 - np.exp(-constants.DAMAGE_CURVE_SCALE_K * stress**constants.DAMAGE_CURVE_SHAPE_ALPHA)


def generate(n_samples: int | None = None) -> pd.DataFrame:
    """Generate the synthetic damage dataset.

    Sampling choices and why they are what they are:

    * ``stress_total`` is drawn uniformly over ``[0, MAX_NORMALISED_HAZARD_INTENSITY]``
      rather than from a realistic distribution of Indian sites. Uniform coverage
      means the model is equally well fitted across the whole range, including the
      high-stress tail where a realistic sample would be sparse and where permit
      decisions actually turn.
    * The three per-hazard stresses are a random partition of the total, so the
      model sees that the same total can arise from very different hazard mixes.
      Without this it could not distinguish a wind-driven site from a flood-driven
      one.
    * ``area_factor`` spans the range ``calculations.area_exposure_factor`` can
      produce for the supported footprint bounds.
    * Noise is multiplicative lognormal, because damage scatter is proportional
      rather than additive — a ±0.05 absolute error means something very different
      at 0.05 damage than at 0.9.

    Args:
        n_samples: Rows to generate. Defaults to ``SYNTHETIC_TRAINING_SAMPLES``.

    Returns:
        A frame with ``FEATURE_COLUMNS`` and ``TARGET_COLUMN``.
    """
    count = n_samples if n_samples is not None else constants.SYNTHETIC_TRAINING_SAMPLES
    rng = new_rng()

    stress_total = rng.uniform(0.0, constants.MAX_NORMALISED_HAZARD_INTENSITY, size=count)

    # Dirichlet gives a uniform random split of the total across the three hazards.
    shares = rng.dirichlet(np.ones(len(constants.HAZARDS)), size=count)
    stress_wind = stress_total * shares[:, 0]
    stress_flood = stress_total * shares[:, 1]
    stress_heat = stress_total * shares[:, 2]

    # Range of area_exposure_factor across the supported footprint bounds.
    area_factor = rng.uniform(0.9, 1.3, size=count)

    baseline = vulnerability_curve(stress_total * area_factor)

    noise = rng.lognormal(mean=0.0, sigma=constants.DAMAGE_OBSERVATION_NOISE_SIGMA, size=count)
    damage = np.clip(
        baseline * noise, constants.MIN_DAMAGE_RATIO, constants.MAX_DAMAGE_RATIO
    )

    return pd.DataFrame(
        {
            "stress_total": stress_total,
            "stress_wind": stress_wind,
            "stress_flood": stress_flood,
            "stress_heat": stress_heat,
            "area_factor": area_factor,
            TARGET_COLUMN: damage,
        }
    )


def main() -> int:
    """Regenerate the dataset on disk and print a summary."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frame = generate()
    destination = DATA_DIR / "synthetic_damage_observations.csv"
    frame.to_csv(destination, index=False)

    print(f"Wrote {len(frame)} synthetic observations to {destination}")
    print("\nSYNTHETIC DATA — see this file's docstring for what its metrics mean.")
    print(frame.describe().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
