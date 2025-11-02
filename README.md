# docman

A CLI tool for organizing documents using AI-powered tools like docling and LLM models.

## Overview

`docman` helps you intelligently organize, move, and rename documents using:
- **docling** for document content extraction and analysis
- **LLM models** for generating intelligent organization suggestions
  - Google Gemini (currently supported)
  - More providers coming soon (Anthropic Claude, OpenAI, local LLMs)
- **Secure credential storage** via OS-native credential managers

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

## Quick Start

1. **Initialize a repository** in your documents directory:
   ```bash
   docman init ~/Documents
   cd ~/Documents
   ```

2. **Set up an LLM provider** (first time only):
   ```bash
   docman llm add
   # Follow the interactive wizard to configure Google Gemini
   ```

3. **Analyze and plan document organization**:
   ```bash
   docman plan
   # docman will analyze your documents and suggest organization improvements
   ```

## Usage

### Basic Commands

```bash
# Check version
docman --version

# See available commands
docman --help

# Initialize a docman repository in a directory
docman init [directory]

# Process documents and generate organization plans
docman plan                    # Process entire repository recursively
docman plan docs/              # Process specific directory (non-recursive)
docman plan docs/ -r           # Process specific directory recursively
docman plan invoice.pdf        # Process single file

# Clear pending operations for a repository
docman reject --all            # Clear all pending operations
docman reject --all -y         # Skip confirmation prompt
```

### LLM Provider Management

`docman` uses LLM models to intelligently analyze and suggest document organization. You can configure multiple LLM providers and switch between them.

```bash
# Add a new LLM provider (interactive wizard)
docman llm add

# Add a provider with command-line options
docman llm add --name my-gemini \
               --provider google \
               --model gemini-1.5-flash \
               --api-key YOUR_API_KEY

# List all configured providers
docman llm list

# Show details of active provider
docman llm show

# Show details of specific provider
docman llm show my-gemini

# Test connection to active provider
docman llm test

# Test connection to specific provider
docman llm test my-gemini

# Switch active provider
docman llm set-active my-gemini

# Remove a provider
docman llm remove my-gemini
docman llm remove my-gemini -y  # Skip confirmation
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

## LLM Provider Setup

### Supported Providers

Currently supported LLM providers:
- **Google Gemini** (via Google AI API)
- More providers coming soon (Anthropic Claude, OpenAI, local LLMs)

### Getting API Keys

#### Google Gemini

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the generated API key
5. Use it when running `docman llm add`

### Security

API keys are stored securely using your operating system's credential manager:
- **macOS**: Keychain
- **Linux**: Secret Service API (GNOME Keyring, KWallet, etc.)
- **Windows**: Windows Credential Manager

Only a reference to the key is stored in the configuration file. The actual API key is never written to disk in plain text.

### Configuration Structure

LLM provider configurations are stored in the app-level config file. Example structure:

```yaml
llm:
  providers:
    - name: google-default
      provider_type: google
      model: gemini-1.5-flash
      is_active: true
    - name: gemini-pro
      provider_type: google
      model: gemini-1.5-pro
      is_active: false
```

### Model Selection

When you run `docman llm add`, the wizard will:
1. Test your API key
2. Fetch the list of available models dynamically from the API
3. Display all models available for your account with descriptions
4. Let you select from the actual available models

This ensures you always see up-to-date models and can only select models you have access to.

#### Typical Google Gemini Models

Common models you may see (availability depends on your API access):
- **gemini-1.5-flash**: Fast, cost-effective, good for most use cases
- **gemini-1.5-pro**: More capable, higher cost, better for complex documents
- **gemini-2.0-flash-exp**: Experimental, latest features
- Other models as they become available

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