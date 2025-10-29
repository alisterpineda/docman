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

# Initialize a docman repository in a directory
docman init [directory]

# Organize documents (coming soon)
docman organize
```

## Configuration

`docman` uses two types of configuration files:

### App Configuration

An application-level configuration file is automatically created the first time you run any `docman` command. This config is stored in an OS-specific location:

- **macOS**: `~/Library/Application Support/docman/config.yaml`
- **Linux**: `~/.config/docman/config.yaml`
- **Windows**: `%APPDATA%\docman\config.yaml`

The app config is used for global settings that apply to all projects.

### Repository Configuration

When you initialize a docman repository in a directory using `docman init`, a repository-specific configuration is created at:

```
<project-directory>/.docman/config.yaml
```

Repository configuration is used for settings specific to that repository/directory.

### Testing Override

For testing purposes, you can override the app config directory location using the `DOCMAN_APP_CONFIG_DIR` environment variable:

```bash
export DOCMAN_APP_CONFIG_DIR=/path/to/custom/config
docman --version
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
│       ├── cli.py
│       └── config.py
├── tests/
│   ├── unit/
│   │   └── test_config.py
│   └── integration/
│       ├── test_init_integration.py
│       └── test_app_config_integration.py
├── pyproject.toml
└── README.md
```

## License

MIT License - see LICENSE file for details.