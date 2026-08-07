"""Every named threshold, weight and physical constant, each with its source documented.

No numeric literal may appear in a service, repository or model wrapper. Everything
lives here with a comment stating where it came from.

Provenance is labelled explicitly on each block:

* ``CODIFIED``   — taken from a published standard or an official classification.
* ``LITERATURE`` — taken from peer-reviewed work, cited inline.
* ``CALIBRATED`` — a product judgement chosen by us. These are the numbers most
  worth challenging, and they are listed in the README's "Known limitations".

Units follow the canonical set in CLAUDE.md: wind m/s, rainfall mm, temperature °C,
area sq ft, coordinates WGS84 (lon, lat).
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Scoring horizon
#
# CALIBRATED. The product's stated window. 2025 is "today" for a permit decision
# and 2055 is a 30-year horizon, which matches the term of a typical Indian home
# loan — the period over which a lender or insurer carries the risk.
# ---------------------------------------------------------------------------
HORIZON_START_YEAR: Final[int] = 2025
HORIZON_END_YEAR: Final[int] = 2055
HORIZON_YEARS: Final[tuple[int, ...]] = tuple(range(HORIZON_START_YEAR, HORIZON_END_YEAR + 1))

# ---------------------------------------------------------------------------
# Hazard reference intensities
#
# Each hazard is normalised to a dimensionless intensity by dividing the projected
# value by its reference. An intensity of 1.0 means "at the reference severity".
# ---------------------------------------------------------------------------

# CODIFIED. IS 875 (Part 3): 2015, Wind Loads on Buildings and Structures — basic
# wind speed for the Chennai / north coastal Tamil Nadu zone, in m/s (3-second gust
# at 10 m above ground, 50-year return period). Structures in this zone are designed
# to this speed, so it is the natural point at which design margin is exhausted.
WIND_REFERENCE_MS: Final[float] = 50.0

# CODIFIED. IMD rainfall classification: "extremely heavy rainfall" is >= 204.5 mm
# in 24 hours. Used as the reference for pluvial flood loading.
RAINFALL_REFERENCE_MM_PER_DAY: Final[float] = 204.5

# CODIFIED. IMD heat wave criteria for the plains: a heat wave is declared when the
# maximum temperature reaches 40 °C. Used as the reference for heat loading.
HEAT_REFERENCE_MAX_TEMP_C: Final[float] = 40.0

# LITERATURE. Sherwood & Huber (2010), "An adaptability limit to climate change due
# to heat stress", PNAS 107(21):9552-9555 — sustained wet-bulb temperature above
# 35 °C exceeds human thermoregulation, i.e. unlivable regardless of construction.
# This is a hard override on the score: no material choice defeats it.
WET_BULB_SURVIVABILITY_LIMIT_C: Final[float] = 35.0

# CALIBRATED. Normalised hazard intensity is clamped to this ceiling. Beyond roughly
# twice the design reference the damage relationship is no longer meaningfully
# resolved by the calibration data, so extrapolating further would imply precision
# the model does not have.
MAX_NORMALISED_HAZARD_INTENSITY: Final[float] = 2.0

# ---------------------------------------------------------------------------
# Building component weights
#
# CALIBRATED, informed by post-cyclone damage surveys, which consistently find that
# envelope failure (roof covering, then roof structure) initiates the damage chain in
# wind events, while foundation and lower-wall condition dominates flood loss. The
# weights must sum to 1.0; `validate_constants()` enforces this at import time.
# ---------------------------------------------------------------------------
COMPONENT_WEIGHTS: Final[dict[str, float]] = {
    "roofing": 0.45,
    "walls": 0.35,
    "foundation": 0.20,
}

# ---------------------------------------------------------------------------
# Per-component hazard sensitivity
#
# CALIBRATED. How much each hazard acts on each component. Rows sum to 1.0.
# Roofing is dominated by wind uplift; foundations by flood scour and saturation;
# walls sit between the two and carry most of the heat-transfer burden.
# ---------------------------------------------------------------------------
COMPONENT_HAZARD_SENSITIVITY: Final[dict[str, dict[str, float]]] = {
    "roofing": {"wind": 0.70, "flood": 0.05, "heat": 0.25},
    "walls": {"wind": 0.30, "flood": 0.35, "heat": 0.35},
    "foundation": {"wind": 0.05, "flood": 0.85, "heat": 0.10},
}

HAZARDS: Final[tuple[str, ...]] = ("wind", "flood", "heat")
BUILDING_COMPONENTS: Final[tuple[str, ...]] = ("foundation", "walls", "roofing")

# ---------------------------------------------------------------------------
# Damage and insurability thresholds
# ---------------------------------------------------------------------------

# CALIBRATED, aligned to catastrophe-modelling practice. A mean damage ratio of 0.40
# corresponds to the point at which repair cost approaches the economic write-off
# point for light residential construction, which is where cover is withdrawn or
# repriced beyond reach. This is the single most consequential number in the product
# and is called out in the README as a product threshold, not a regulatory one.
UNINSURABLE_DAMAGE_RATIO: Final[float] = 0.40

# CALIBRATED. Damage ratio is a physical quantity bounded to [0, 1]; predictions from
# the calibration model are clamped to this range.
MIN_DAMAGE_RATIO: Final[float] = 0.0
MAX_DAMAGE_RATIO: Final[float] = 1.0

# ---------------------------------------------------------------------------
# Exposure scaling by floor area
#
# CALIBRATED. Larger footprints present more envelope to wind and more slab to
# flooding, but loss ratio scales far more weakly than area. A logarithmic term
# anchored at a reference footprint captures that without letting a large building
# dominate the score.
# ---------------------------------------------------------------------------
# Median independent-house plot area in urban Tamil Nadu, in sq ft (a 30x40 ft plot).
REFERENCE_FLOOR_AREA_SQ_FT: Final[float] = 1200.0
AREA_EXPOSURE_COEFFICIENT: Final[float] = 0.08
MIN_FLOOR_AREA_SQ_FT: Final[float] = 100.0
MAX_FLOOR_AREA_SQ_FT: Final[float] = 1_000_000.0

# ---------------------------------------------------------------------------
# Geometry validation
#
# CALIBRATED bounds for untrusted polygon input.
# ---------------------------------------------------------------------------
# A closed GeoJSON linear ring repeats its first point, so a triangle has 4 entries.
MIN_POLYGON_RING_POINTS: Final[int] = 4
# Guards against a client posting a multi-megabyte traced coastline.
MAX_POLYGON_RING_POINTS: Final[int] = 1_000
# Polygon area is bounded by MIN/MAX_FLOOR_AREA_SQ_FT above. A second pair of
# bounds in square metres would be a duplicate that could drift out of agreement
# with the database CHECK constraint, so there deliberately isn't one.

# WGS84 valid coordinate ranges (EPSG:4326).
MIN_LONGITUDE: Final[float] = -180.0
MAX_LONGITUDE: Final[float] = 180.0
MIN_LATITUDE: Final[float] = -90.0
MAX_LATITUDE: Final[float] = 90.0

# The spatial reference the whole system stores and exchanges geometry in.
WGS84_SRID: Final[int] = 4326

# ---------------------------------------------------------------------------
# Unit conversions
#
# CODIFIED. Exact by international definition (1 inch = 25.4 mm exactly).
# ---------------------------------------------------------------------------
SQ_METRES_PER_SQ_FOOT: Final[float] = 0.09290304
SQ_FEET_PER_SQ_METRE: Final[float] = 1.0 / SQ_METRES_PER_SQ_FOOT

# CODIFIED. IMD publishes wind speeds in km/h; internal calculations use m/s.
MS_PER_KMPH: Final[float] = 1000.0 / 3600.0

# CODIFIED. Exact by definition of the Celsius scale. CMIP6 temperature bands are
# published in kelvin; the internal unit is degrees Celsius.
KELVIN_TO_CELSIUS_OFFSET: Final[float] = 273.15

# CODIFIED. CMIP6 precipitation is a flux in kg m-2 s-1, numerically equal to mm/s
# for liquid water. Multiplying by the seconds in a day gives mm/day.
SECONDS_PER_DAY: Final[float] = 86_400.0

# ---------------------------------------------------------------------------
# Earth Engine datasets
#
# CODIFIED dataset identifiers, CALIBRATED choices of scenario and band.
# ---------------------------------------------------------------------------
# NASA Earth Exchange Global Daily Downscaled Projections. Daily, ~25 km, and the
# standard downscaled CMIP6 product for local impact work.
EARTH_ENGINE_CMIP6_DATASET: Final[str] = "NASA/GDDP-CMIP6"

# CALIBRATED. SSP2-4.5 is the "middle of the road" pathway. A permit decision needs
# a central estimate rather than a worst case: scoring every site against SSP5-8.5
# would declare almost everything uninsurable and make the tool useless for
# comparing material choices, which is its actual purpose.
EARTH_ENGINE_CMIP6_SCENARIO: Final[str] = "ssp245"

# CALIBRATED. A multi-model subset rather than one model, because single-model
# projections carry structural bias. The spread across these members is what the
# reported confidence interval is derived from.
EARTH_ENGINE_CMIP6_MODELS: Final[tuple[str, ...]] = (
    "ACCESS-CM2",
    "MPI-ESM1-2-HR",
    "MRI-ESM2-0",
    "NorESM2-MM",
)

# CODIFIED. Band names as published in NASA/GDDP-CMIP6.
EARTH_ENGINE_BAND_MAX_TEMPERATURE: Final[str] = "tasmax"  # kelvin
EARTH_ENGINE_BAND_PRECIPITATION: Final[str] = "pr"  # kg m-2 s-1
EARTH_ENGINE_BAND_WIND_SPEED: Final[str] = "sfcWind"  # m/s at 10 m
EARTH_ENGINE_BAND_RELATIVE_HUMIDITY: Final[str] = "hurs"  # percent

# CALIBRATED. Radius in metres over which band values are reduced around the site
# centroid. Smaller than one CMIP6 grid cell, so the value reflects the cell the
# site sits in rather than averaging neighbouring cells.
EARTH_ENGINE_SAMPLE_RADIUS_M: Final[float] = 1_000.0

# ---------------------------------------------------------------------------
# IMD cyclone intensity classification
#
# CODIFIED. India Meteorological Department cyclone categories, defined by
# 3-minute sustained surface wind in km/h. Stored as lower bounds, ascending.
# Used to interpret IMD historical records and to label projected intensities.
# ---------------------------------------------------------------------------
# CALIBRATED. Tolerance applied when comparing a speed against a category bound.
# Internal wind speeds are metres per second, so classifying one means converting
# back to km/h — and that round trip is not exact in binary floating point (31 km/h
# returns as 30.999999999999996). Without this tolerance a speed sitting exactly on
# a boundary would be classified one category too low. A micro-km/h is far below any
# meaningful measurement precision, so it cannot mask a real difference.
CYCLONE_CATEGORY_BOUNDARY_TOLERANCE_KMPH: Final[float] = 1e-6

IMD_CYCLONE_CATEGORIES_KMPH: Final[tuple[tuple[str, float], ...]] = (
    ("Depression", 31.0),
    ("Deep Depression", 51.0),
    ("Cyclonic Storm", 62.0),
    ("Severe Cyclonic Storm", 89.0),
    ("Very Severe Cyclonic Storm", 118.0),
    ("Extremely Severe Cyclonic Storm", 166.0),
    ("Super Cyclonic Storm", 222.0),
)

# ---------------------------------------------------------------------------
# External data caching
#
# CALIBRATED. Cache entries key on the site centroid rounded to this precision, so
# two sites a few metres apart reuse one upstream response. Five decimal places is
# roughly 1.1 m at the equator — finer than any climate grid cell, so rounding
# cannot merge genuinely different climate conditions.
# ---------------------------------------------------------------------------
CACHE_COORDINATE_PRECISION_DP: Final[int] = 5

# CALIBRATED. CMIP6 projections are republished on a multi-year cadence and IMD
# historical records are appended seasonally, so a 30-day life keeps results stable
# within a permit cycle while still picking up upstream revisions.
CACHE_TTL_DAYS: Final[int] = 30

# ---------------------------------------------------------------------------
# External call policy
#
# CALIBRATED. Earth Engine aggregations are slow, so it gets a longer budget than a
# plain REST call. Retries use exponential backoff and apply only to transient
# failures (timeouts, 5xx, 429) — never to a 4xx, which would just fail again.
# ---------------------------------------------------------------------------
EXTERNAL_REQUEST_TIMEOUT_SECONDS: Final[float] = 10.0
EARTH_ENGINE_TIMEOUT_SECONDS: Final[float] = 60.0
GEMINI_TIMEOUT_SECONDS: Final[float] = 30.0
# CALIBRATED. The prompt caps the report at 400 words; this token ceiling leaves
# comfortable headroom above that while bounding cost and latency.
GEMINI_MAX_OUTPUT_TOKENS: Final[int] = 1_200
EXTERNAL_MAX_RETRY_ATTEMPTS: Final[int] = 3
EXTERNAL_RETRY_INITIAL_BACKOFF_SECONDS: Final[float] = 0.5
EXTERNAL_RETRY_MAX_BACKOFF_SECONDS: Final[float] = 8.0
RETRYABLE_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})

# ---------------------------------------------------------------------------
# Damage vulnerability curve
#
# CALIBRATED. The relationship between resistance-weighted stress and expected
# damage ratio follows the exponential vulnerability form used throughout
# catastrophe modelling:
#
#     damage = 1 - exp(-k * stress^alpha)
#
# The two coefficients are fixed by two anchor points we chose deliberately:
#
#   stress 1.0 (the full design load reaches the structure) -> damage 0.35
#   stress 2.0 (twice the design load)                      -> damage 0.75
#
# Below the uninsurability threshold at exactly the design load, above it well
# before twice the design load. These generate the synthetic training data in
# /ml, so the damage model learns this curve — see the README's honest note about
# what that does and does not demonstrate.
# ---------------------------------------------------------------------------
DAMAGE_CURVE_SCALE_K: Final[float] = 0.4308
DAMAGE_CURVE_SHAPE_ALPHA: Final[float] = 1.6861

# CALIBRATED. Multiplicative lognormal spread applied when generating synthetic
# damage observations, representing the scatter real post-event damage surveys show
# around any fitted vulnerability curve.
DAMAGE_OBSERVATION_NOISE_SIGMA: Final[float] = 0.15

# CALIBRATED. Size of the synthetic training set. Large enough for the ensemble to
# converge, small enough to retrain in seconds on a laptop.
SYNTHETIC_TRAINING_SAMPLES: Final[int] = 6_000
TRAIN_TEST_SPLIT_FRACTION: Final[float] = 0.2

# CALIBRATED. Random forest hyperparameters. The ensemble is deliberately shallow:
# the underlying relationship is smooth and low-dimensional, so deeper trees would
# fit noise without improving held-out error, and the per-tree spread is what the
# reported confidence interval is derived from.
DAMAGE_MODEL_N_ESTIMATORS: Final[int] = 200
DAMAGE_MODEL_MAX_DEPTH: Final[int] = 8
DAMAGE_MODEL_MIN_SAMPLES_LEAF: Final[int] = 5

RANKER_MODEL_N_ESTIMATORS: Final[int] = 150
RANKER_MODEL_MAX_DEPTH: Final[int] = 6

# ---------------------------------------------------------------------------
# Rate limiting
#
# CALIBRATED. How often the limiter sweeps expired per-client windows out of memory.
# Sweeping on every request would rescan the map under load; sweeping too rarely
# lets it grow. Thirty seconds keeps the map small without measurable overhead.
# ---------------------------------------------------------------------------
RATE_LIMIT_PRUNE_INTERVAL_SECONDS: Final[float] = 30.0

# ---------------------------------------------------------------------------
# Determinism
#
# CALIBRATED. A fixed seed for every stochastic operation (model training, synthetic
# data generation, any sampled uncertainty), so identical inputs always produce
# identical outputs as the brief requires.
# ---------------------------------------------------------------------------
RANDOM_SEED: Final[int] = 20231204  # Cyclone Michaung's Chennai landfall, 4 Dec 2023

# ---------------------------------------------------------------------------
# Model confidence reporting
#
# CALIBRATED. Predictions are reported with a confidence band derived from the
# ensemble's prediction spread. These bounds keep the reported band honest: never
# claimed tighter than the model's own test-set error, never so wide as to be
# useless.
# ---------------------------------------------------------------------------
MIN_CONFIDENCE_INTERVAL_WIDTH: Final[float] = 0.02
MAX_CONFIDENCE_INTERVAL_WIDTH: Final[float] = 0.50
CONFIDENCE_INTERVAL_Z_SCORE: Final[float] = 1.96  # two-sided 95% interval, normal approx.

# CALIBRATED. Qualitative confidence labels attached to a score, by the width of the
# uncertainty band on the crossing year in years.
CONFIDENCE_LABEL_THRESHOLDS_YEARS: Final[tuple[tuple[str, float], ...]] = (
    ("high", 3.0),
    ("moderate", 7.0),
    ("low", float("inf")),
)


def validate_constants() -> None:
    """Assert the internal consistency this module's callers rely on.

    Called at application startup. A weight table that silently stopped summing to
    1.0 would bias every score in a way no test of a single function would catch.

    Raises:
        ValueError: If any weighting table is inconsistent.
    """
    component_total = sum(COMPONENT_WEIGHTS.values())
    if abs(component_total - 1.0) > 1e-9:
        raise ValueError(f"COMPONENT_WEIGHTS must sum to 1.0, got {component_total}")

    if set(COMPONENT_WEIGHTS) != set(BUILDING_COMPONENTS):
        raise ValueError("COMPONENT_WEIGHTS keys must match BUILDING_COMPONENTS")

    if set(COMPONENT_HAZARD_SENSITIVITY) != set(BUILDING_COMPONENTS):
        raise ValueError("COMPONENT_HAZARD_SENSITIVITY keys must match BUILDING_COMPONENTS")

    for component, sensitivities in COMPONENT_HAZARD_SENSITIVITY.items():
        if set(sensitivities) != set(HAZARDS):
            raise ValueError(f"COMPONENT_HAZARD_SENSITIVITY[{component!r}] must cover all hazards")
        total = sum(sensitivities.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"COMPONENT_HAZARD_SENSITIVITY[{component!r}] must sum to 1.0, got {total}"
            )

    if HORIZON_START_YEAR >= HORIZON_END_YEAR:
        raise ValueError("HORIZON_START_YEAR must be before HORIZON_END_YEAR")

    if not MIN_DAMAGE_RATIO < UNINSURABLE_DAMAGE_RATIO < MAX_DAMAGE_RATIO:
        raise ValueError("UNINSURABLE_DAMAGE_RATIO must lie strictly within the damage range")
