# Claude Runner

FastAPI backend for Claude's Home.

## Development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 18+ (for git hooks)

### Setup

```bash
# Install Python dependencies
uv sync --dev

# Install git hooks
npm install
```

### Running

```bash
# Development server
uv run python -m api

# Or with uvicorn directly
uv run uvicorn api.app:create_app --factory --reload
```

### Quality Checks

```bash
# Lint
uv run ruff check src tests

# Format
uv run black src tests
uv run isort src tests

# Type check
uv run mypy src

# Tests
uv run pytest

# Protocol Zero compliance
./tools/protocol-zero.sh
```

## API Documentation

When running in debug mode, API docs are available at `/api/v1/docs`.

## License

Private - All rights reserved.
