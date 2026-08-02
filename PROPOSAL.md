# Zenovators

**Tech for Good 2026** · GDG Coimbatore · Build weekend Aug 8–9, GRD College

**Track:** AI for Sustainable Cities & Climate Action
**Team code:** TEAM-263

## Problem

Cities approve buildings using today's climate data and don't check if they'll survive their own 20–40 year lifespan.

## Who it helps

Building Permit Reviewers at municipal corporations (e.g., Greater Chennai Corporation) who manually check submitted building plans against flood-hazard maps with no forward-looking climate data, slowing every approval.

## Solution

- Enter an address in Chennai → the system pulls real CMIP6 flood/precipitation projections for that exact location via Google Earth Engine.
- A machine learning model, trained on historical rainfall and flood-incident data for Tamil Nadu, predicts the year this specific site crosses a defined severe-flood-risk threshold — rather than reading a fixed value off a single projection curve — replacing the manual, static hazard-map cross-check a Building Permit Reviewer currently does by hand.
- Demo: type an address, see it plotted on a map, drag a 2025–2055 timeline, watch the flood-risk trajectory and the year it crosses "severe" flash on screen — a clear before/after in under 90 seconds.
- Output is a single score card usable directly at the point of permit review, not a public awareness map.
- Post-hackathon: share the score card with 2–3 architects or municipal contacts for feedback on accuracy and format, then approach Greater Chennai Corporation's Town Planning division for a pilot conversation.

## Architecture

React web app (address input + map + timeline) → FastAPI backend → Google Earth Engine (CMIP6 flood/precipitation projections for the coordinate) → ML model (scikit-learn, trained on historical rainfall + flood-incident data) predicts the severe-risk-crossing year → PostGIS (spatial risk storage) → PostgreSQL (store the computed score per address).

## Tech stack

React, FastAPI, PostGIS, Google Earth Engine, scikit-learn

## Getting started

1. Accept your collaborator invite (check your email / GitHub notifications).
2. Clone this repo and start building.
3. Commit early and often — this repo is what you present on the day.

---

_Created automatically when your proposal was validated._