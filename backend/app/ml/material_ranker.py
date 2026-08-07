"""Inference wrapper for the material ranking model used to recommend materials.

The model predicts how much damage a candidate material removes for a given hazard
profile. Cost is applied here, outside the model, so the ranking policy —
damage-reduction per unit of relative cost — is visible and changeable without
retraining.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.core import constants
from app.core.logging import get_logger
from app.ml.registry import LoadedModel

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RankedMaterial:
    """A candidate material scored for a specific site and component.

    Attributes:
        code: Catalogue code.
        component: Component it was evaluated for.
        predicted_damage_reduction: Damage ratio removed, versus no resistance.
        relative_cost_index: Installed cost relative to the conventional option.
        value_score: Damage reduction per unit of relative cost. The ranking key.
    """

    code: str
    component: str
    predicted_damage_reduction: float
    relative_cost_index: float
    value_score: float


class MaterialRankerModel:
    """Ranks candidate materials against a hazard profile."""

    def __init__(self, loaded: LoadedModel) -> None:
        """Bind the wrapper to a loaded artifact."""
        self._loaded = loaded

    @property
    def version(self) -> str:
        """Artifact version, recorded on every score."""
        return self._loaded.version

    def rank(
        self,
        *,
        hazard_intensities: dict[str, float],
        candidates: list[dict[str, object]],
    ) -> list[RankedMaterial]:
        """Rank candidate materials by damage reduction per unit cost.

        Args:
            hazard_intensities: Peak normalised intensity per hazard for this site.
            candidates: One mapping per candidate with ``code``, ``component``,
                ``resistance`` (a hazard-keyed mapping) and ``relative_cost_index``.

        Returns:
            Candidates sorted by ``value_score``, best first.

        Raises:
            ValueError: If a hazard intensity is missing, which would otherwise be
                treated as zero risk and distort every recommendation.
        """
        missing = set(constants.HAZARDS) - set(hazard_intensities)
        if missing:
            raise ValueError(f"missing hazard intensities: {sorted(missing)}")

        if not candidates:
            return []

        rows: list[list[float]] = []
        for candidate in candidates:
            component = str(candidate["component"])
            resistance = candidate["resistance"]
            if not isinstance(resistance, dict):
                raise ValueError(f"candidate {candidate.get('code')!r} has no resistance mapping")

            sensitivity = constants.COMPONENT_HAZARD_SENSITIVITY[component]
            feature_values = {
                "intensity_wind": hazard_intensities["wind"],
                "intensity_flood": hazard_intensities["flood"],
                "intensity_heat": hazard_intensities["heat"],
                "component_weight": constants.COMPONENT_WEIGHTS[component],
                "sensitivity_wind": sensitivity["wind"],
                "sensitivity_flood": sensitivity["flood"],
                "sensitivity_heat": sensitivity["heat"],
                "resistance_wind": float(resistance["wind"]),
                "resistance_flood": float(resistance["flood"]),
                "resistance_heat": float(resistance["heat"]),
            }
            rows.append([feature_values[column] for column in self._loaded.feature_columns])

        reductions = self._loaded.estimator.predict(np.array(rows, dtype=float))

        ranked: list[RankedMaterial] = []
        for candidate, reduction in zip(candidates, reductions, strict=True):
            cost = float(candidate["relative_cost_index"])  # type: ignore[arg-type]
            benefit = max(0.0, float(reduction))
            ranked.append(
                RankedMaterial(
                    code=str(candidate["code"]),
                    component=str(candidate["component"]),
                    predicted_damage_reduction=benefit,
                    relative_cost_index=cost,
                    # Cost is positive by database constraint, so this cannot divide
                    # by zero. Ranking on benefit-per-cost rather than raw benefit
                    # stops the recommendation always being the most expensive option.
                    value_score=benefit / cost,
                )
            )

        # Sorted by value, then by cost ascending so an exact tie prefers the
        # cheaper material, then by code so the order is fully deterministic.
        ranked.sort(key=lambda item: (-item.value_score, item.relative_cost_index, item.code))
        return ranked
