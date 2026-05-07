# Axiom Platform

AI-powered autonomous platform for Autodesk Revit MEP/S/A/T workflows.

## Overview

Axiom is an intelligent automation platform that transforms how MEP engineers interact with Revit. It provides autonomous execution of complex workflows like project setup, view creation, device placement, and eventually duct/pipe routing - all with built-in safety, simulation, and learning capabilities.

## Architecture

The platform follows a layered architecture:

- **Input Normalization Layer**: Transforms Excel/CSV/JSON inputs into validated job objects
- **Orchestration Layer**: Converts jobs into execution plans and coordinates workflow
- **MCP Layer**: Tool protocol boundary for Revit operations (mock implementation for testing)
- **Persistence Layer**: SQLite-backed storage with WAL mode for concurrent read/write access

## Current Status

This is a proof-of-concept implementation that demonstrates the core architecture:

- Input normalization from Excel files
- Plan generation for PROJECT_SETUP workflows
- Mock tool execution with simulation
- QA evaluation and reporting
- CLI for job submission and monitoring
- SQLite persistence with WAL mode (data survives restarts)

Data is stored in `~/.axiom/axiom.db` by default. Override with the `AXIOM_DB_PATH` environment variable.

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/axiom-platform.git
cd axiom-platform

# Install dependencies with Poetry
poetry install

# Run the CLI
poetry run axiom --help
```

## Usage

### Submit a job from Excel

```bash
poetry run axiom submit path/to/project_inputs.xlsx --firm-id my_firm
```

### Generate a plan

```bash
poetry run axiom plan <job_id> --approve
```

### Execute (simulate) a plan

```bash
poetry run axiom execute <plan_id>
```

### Run a complete demo

```bash
poetry run axiom demo path/to/project_inputs.xlsx
```

### View available tools

```bash
poetry run axiom tools
```

### View statistics

```bash
poetry run axiom stats
```

## Excel Input Format

The input Excel file should contain columns for:

- Project Number
- Project Name
- Project Revit Version (e.g., 2023)
- Is this an ACC project? (Yes/No)
- Indicate what views will be needed (semicolon-separated, e.g., "E - General;M - HVAC")
- Will the footprint be divided by areas (scope box description)
- Engineer stamp
- Team assignments
- BIM Execution Plan path
- Sheet list path
- Additional comments

## Development

### Run tests

```bash
poetry run pytest
```

### Run linting

```bash
poetry run ruff check src tests
poetry run black --check src tests
```

### Type checking

```bash
poetry run mypy src
```

## Project Structure

```
axiom-platform/
├── src/
│   ├── axiom_core/           # Core platform components
│   │   ├── schemas.py        # Data models (Job, Plan, ToolStep, etc.)
│   │   ├── input_normalization.py  # Excel/CSV parsing
│   │   ├── orchestrator.py   # Plan generation and execution
│   │   ├── mcp_layer.py      # Mock Revit tool layer
│   │   ├── models.py         # SQLAlchemy ORM models
│   │   ├── database.py       # Engine/session management (WAL mode)
│   │   └── persistence.py    # SQLite-backed storage
│   └── axiom_cli/            # Command-line interface
│       └── main.py
├── tests/                    # Test suite
├── docs/                     # Documentation
└── pyproject.toml           # Project configuration
```

## Roadmap

### Phase 1 (Complete)
- Core architecture and schemas
- Input normalization
- Mock MCP layer
- CLI interface
- SQLite persistence with WAL mode

### Phase 2 (Current)
- Real Revit connector (C# add-in)
- Basic Project Setup workflow

### Phase 3
- ACC/APS integration
- ALES learning system
- Advanced workflows (device placement)

### Phase 4
- Duct/pipe routing
- Full autonomous mode
- Multi-firm deployment

## License

Proprietary - All rights reserved.
