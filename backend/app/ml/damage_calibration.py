"""Inference wrapper for the damage calibration regressor.

Returns a prediction plus a genuine uncertainty estimate. The brief forbids
presenting a point estimate as certain, and a random forest supplies the necessary
spread directly: each tree is a separate estimate, so their standard deviation is a
real measure of how much the ensemble disagrees at that point in feature space.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.core import calculations
from app.core.logging import get_logger
from app.ml.registry import LoadedModel

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DamagePrediction:
    """A predicted damage ratio with its uncertainty.

    Attributes:
        damage_ratio: Point estimate, clamped to ``[0, 1]``.
        standard_error: Standard deviation across the ensemble's trees.
        lower: Lower bound of the 95% interval, clamped to ``[0, 1]``.
        upper: Upper bound of the 95% interval, clamped to ``[0, 1]``.
    """

    damage_ratio: float
    standard_error: float
    lower: float
    upper: float


class DamageCalibrationModel:
    """Turns resistance-weighted stress into an expected damage ratio."""

    def __init__(self, loaded: LoadedModel) -> None:
        """Bind the wrapper to a loaded artifact."""
        self._loaded = loaded

    @property
    def version(self) -> str:
        """Artifact version, recorded on every score."""
        return self._loaded.version

    def predict(
        self,
        *,
        stress_total: float,
        stress_wind: float,
        stress_flood: float,
        stress_heat: float,
        area_factor: float,
    ) -> DamagePrediction:
        """Predict the damage ratio for one year's stress.

        Args:
            stress_total: Total resistance-weighted stress.
            stress_wind: Portion attributable to wind.
            stress_flood: Portion attributable to flood.
            stress_heat: Portion attributable to heat.
            area_factor: Footprint exposure multiplier.

        Returns:
            The prediction and its 95% interval.
        """
        return self.predict_many(
            [
                {
                    "stress_total": stress_total,
                    "stress_wind": stress_wind,
                    "stress_flood": stress_flood,
                    "stress_heat": stress_heat,
                    "area_factor": area_factor,
                }
            ]
        )[0]

    def predict_many(self, rows: list[dict[str, float]]) -> list[DamagePrediction]:
        """Predict for many rows in one call.

        A score spans 31 years, so batching turns 31 estimator calls into one. That
        is the difference between a responsive endpoint and a sluggish one.

        Args:
            rows: One mapping per row, keyed by the artifact's feature names.

        Returns:
            Predictions in the same order as ``rows``.

        Raises:
            ValueError: If a row is missing a feature the artifact expects.
        """
        if not rows:
            return []

        missing = set(self._loaded.feature_columns) - set(rows[0])
        if missing:
            raise ValueError(f"missing features for damage prediction: {sorted(missing)}")

        # Column order is part of the artifact's contract: estimators index
        # features positionally, so building the matrix from feature_columns is
        # what stops a reordering from silently mis-predicting.
        matrix = np.array(
            [[row[column] for column in self._loaded.feature_columns] for row in rows],
            dtype=float,
        )

        estimator = self._loaded.estimator
        means = estimator.predict(matrix)

        # Per-tree predictions give the ensemble's own disagreement, which is a
        # real uncertainty signal rather than an assumed constant.
        per_tree = np.stack([tree.predict(matrix) for tree in estimator.estimators_])
        deviations = per_tree.std(axis=0)

        predictions: list[DamagePrediction] = []
        for mean, deviation in zip(means, deviations, strict=True):
            lower, upper = calculations.confidence_interval(float(mean), float(deviation))
            predictions.append(
                DamagePrediction(
                    damage_ratio=calculations.clamp_damage_ratio(float(mean)),
                    standard_error=float(deviation),
                    lower=calculations.clamp_damage_ratio(lower),
                    upper=calculations.clamp_damage_ratio(upper),
                )
            )
        return predictions
