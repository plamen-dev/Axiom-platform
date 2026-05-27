# Axiom Platform

Axiom Platform is a safety-first Autodesk Revit automation prototype. The current prototype combines a Revit add-in, prompt-driven capabilities, model inventory and parameter discovery, a local validation runner, and repo-native evidence workflows.

This repository is the working codebase for **Axiom Prototype v1**.

## Current Capabilities

Axiom currently includes:

- Revit ribbon/add-in integration for supported Revit versions.
- Prompt-driven Revit capability execution.
- `CreateGrids` capability.
- `CreateLevels` capability.
- `InventoryModel` capability.
- Object schema discovery.
- Category-by-category parameter schema discovery.
- Parameter registry build workflow.
- Local Runner for repeatable allowlisted validation tasks.
- PR evidence snapshot workflow for durable development/evidence records.

## Validated Registry Milestone

The current registry milestone was validated using five Snowdon Towers source models across architectural, electrical, HVAC, plumbing, and structural disciplines.

Validated results:

- 5 Snowdon source models.
- 278 successful full-plan category exports.
- 0 duplicate export paths.
- 6,444 unique parameter/property definitions.
- 1,878 unique parameter names.
- 1,748 imported runs.
- 20/20 priority categories executed.
- 20/20 priority categories with definitions.

These results are documented in the repo evidence logs and runbooks.

## Safety Model

Axiom is intentionally safety-first. Broad unsafe extraction and model-wide operations are blocked unless routed through controlled workflows.

Current safety rules include:

- Full unsafe `InventoryModel` execution is blocked.
- Whole-model sample value extraction is blocked.
- Whole-model parameter schema extraction is blocked.
- Safe category-by-category parameter schema execution is supported through the planned execution queue.
- Local Runner uses allowlisted actions only.
- Local Runner does not allow arbitrary shell execution.
- Live Revit validation remains human-supervised.

## Quick Start

Install dependencies:

```bash
poetry install
