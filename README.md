# docman

A CLI tool for organizing documents using AI-powered tools like docling and LLM models.

## Overview

`docman` helps you intelligently organize, move, and rename documents using:
- **docling** for document processing and analysis
- **LLM models** via cloud SDKs (e.g., Anthropic) or local LLMs

## Installation

### Prerequisites
- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) (recommended for package management)

### Install with uv

```bash
# Clone the repository
git clone <repository-url>
cd docman

# Install in development mode
uv sync

# Or install with dev dependencies
uv sync --all-extras
```

### Install with pip

```bash
pip install -e .
```

## Usage

After installation, the `docman` command will be available:

```bash
# Check version
docman --version

# See available commands
docman --help

# Organize documents (coming soon)
docman organize
```

## Development

### Setup

```bash
# Install with development dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linter
uv run ruff check .

# Run type checker
uv run mypy src/
```

### Project Structure

```
docman/
├── src/
│   └── docman/
│       ├── __init__.py
│       └── cli.py
├── tests/
├── pyproject.toml
└── README.md
```

## License

MIT License - see LICENSE file for details.