# Prompt Engineering Analysis: Medium Priority Improvements

**Analysis Date:** 2025-11-20
**Scope:** docman LLM prompt system optimization and enhancement

---

## Executive Summary

This document identifies medium-priority improvements that enhance prompt effectiveness, caching efficiency, and provider-specific optimizations. These improvements build on a stable foundation and provide incremental quality and performance gains.

---

## 1. Caching and Performance Optimizations

### 1.1 Organization Instructions Not Cached

**Location:** `src/docman/prompt_builder.py`

**Issue:** Organization instructions are regenerated on every call:

```python
def generate_instructions(repo_root: Path) -> str | None:
    folder_definitions = get_folder_definitions(repo_root)
    if not folder_definitions:
        return None

    default_filename_convention = get_default_filename_convention(repo_root)
    return generate_instructions_from_folders(
        folder_definitions, repo_root, default_filename_convention
    )
```

**Problem:** For batch operations (e.g., planning 100 documents), this:
- Rereads config file 100 times
- Regenerates markdown instructions 100 times
- Re-detects existing directories 100 times (filesystem traversal)

**Impact:**
- Unnecessary I/O operations
- Performance degradation for large batches
- Repeated filesystem traversals

**Recommendation:** Add caching with config file mtime check:

```python
_instructions_cache: dict[str, tuple[float, str]] = {}

def generate_instructions(repo_root: Path) -> str | None:
    config_path = repo_root / ".docman" / "config.yaml"
    config_mtime = config_path.stat().st_mtime if config_path.exists() else 0

    cache_key = str(repo_root)
    if cache_key in _instructions_cache:
        cached_mtime, cached_result = _instructions_cache[cache_key]
        if cached_mtime == config_mtime:
            return cached_result

    # Generate instructions...
    result = generate_instructions_from_folders(...)
    _instructions_cache[cache_key] = (config_mtime, result)
    return result
```

---

### 1.2 Existing Directory Detection Repeated Unnecessarily

**Location:** `src/docman/prompt_builder.py` - `_detect_existing_directories()`

**Issue:** For each batch of documents, this function traverses the filesystem to find existing directory values for variable patterns.

**Problem:** Within a single `plan` command execution, the filesystem is unlikely to change, yet this traversal happens for each instruction generation.

**Recommendation:** Cache directory detection per session or use the same caching mechanism as above.

---

### 1.3 Template Loading on Every Call

**Location:** `src/docman/prompt_builder.py`

**Issue:** Templates are loaded via `_template_env.get_template()` on each call:

```python
def build_user_prompt(...) -> str:
    template = _template_env.get_template("user_prompt.j2")
    return template.render(...)
```

**Note:** Jinja2's `Environment` does cache compiled templates, so this is less severe than it appears. However, explicit caching could further optimize.

**Recommendation:** Pre-load templates at module level:

```python
_system_prompt_template = _template_env.get_template("system_prompt.j2")
_user_prompt_template = _template_env.get_template("user_prompt.j2")
```

---

## 2. Variable Pattern Handling Enhancements

### 2.1 Existing Values Limited to 10

**Location:** `src/docman/prompt_builder.py` - `_detect_existing_directories()`

**Issue:** Only first 10 existing directory values are shown:

```python
dir_names = sorted(dir_names)[:10]
```

**Problem:** For frequently used variable patterns (e.g., years, clients), important values may be truncated.

**Impact:**
- LLM may create duplicates of existing values it doesn't see
- Inconsistent behavior depending on which 10 values are shown

**Recommendation:**
1. Show all values for small sets (≤20)
2. For larger sets, show most recent + note truncation:

```python
if len(dir_names) <= 20:
    display_names = sorted(dir_names)
else:
    # Sort by modification time, show most recent
    display_names = sorted(dir_names, key=lambda d: ...)[:15]
    display_names.append(f"... and {len(dir_names) - 15} more")
```

Or indicate truncation in the prompt:
```
Existing: 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 (showing 8 of 20)
```

---

### 2.2 Pattern Name Inference for Undefined Patterns

**Location:** `src/docman/prompt_builder.py` - `_get_pattern_guidance()`

**Issue:** Undefined patterns get generic fallback guidance:

```python
return f"\n  - Infer {variable_name} from document context"
```

**Opportunity:** Common pattern names could have better default guidance:

| Pattern Name | Better Default Guidance |
|-------------|------------------------|
| `year` | "4-digit year in YYYY format (e.g., 2024)" |
| `month` | "2-digit month in MM format (01-12)" |
| `date` | "Date in YYYY-MM-DD format" |
| `company` | "Company or organization name from document header" |
| `client` | "Client name from document" |

**Recommendation:**

```python
DEFAULT_PATTERN_HINTS = {
    "year": "4-digit year in YYYY format (e.g., 2024)",
    "month": "2-digit month in MM format (01-12)",
    "day": "2-digit day in DD format (01-31)",
    "date": "Date in YYYY-MM-DD format",
    "company": "Company or organization name",
    "client": "Client name from document",
    "category": "Document category or type",
    "description": "Brief description of document content",
}

def _get_pattern_guidance(variable_name: str, repo_root: Path) -> str:
    patterns = get_variable_patterns(repo_root)
    if variable_name in patterns:
        # Use user-defined guidance
        ...
    elif variable_name.lower() in DEFAULT_PATTERN_HINTS:
        # Use intelligent default
        return f"\n  - {DEFAULT_PATTERN_HINTS[variable_name.lower()]}"
    else:
        # Generic fallback
        return f"\n  - Infer {variable_name} from document context"
```

---

### 2.3 Variable Pattern Values Without Aliases Not Highlighted

**Issue:** When patterns have predefined values without aliases, the prompt format is basic:

```
**company**:
  - Company name from document
  - Known values:
    - "Acme Corp." - Main company
    - "Beta Industries" - Partner
```

**Opportunity:** For values without aliases, could still indicate canonical status:

```
  - Known values:
    - "Acme Corp." - Main company (canonical)
```

This helps the LLM understand that these are preferred forms.

---

## 3. Provider-Specific Prompt Optimizations

### 3.1 Different Prompt Structures for Different Providers

**Location:** `src/docman/llm_providers.py`

**Issue:** Google Gemini and OpenAI handle prompts differently:

- **Gemini:** Combines system + user into single prompt
- **OpenAI:** Separate system/user messages

**Current Implementation:**
```python
# Gemini
combined_prompt = f"{system_prompt}\n\n{user_prompt}"
response = self.model.generate_content(combined_prompt)

# OpenAI
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
]
```

**Opportunity:** Optimize prompt structure per provider:

1. **Gemini:** Could use explicit section markers since it's a single prompt
2. **OpenAI:** Could use multiple user messages for long content

**Recommendation:** Add provider-specific prompt formatters:

```python
class GoogleGeminiProvider(LLMProvider):
    def format_prompts(self, system_prompt: str, user_prompt: str) -> str:
        return f"""=== SYSTEM INSTRUCTIONS ===
{system_prompt}

=== USER REQUEST ===
{user_prompt}"""
```

---

### 3.2 Temperature Not Configurable

**Issue:** Temperature is hardcoded or uses defaults:
- OpenAI: `temperature=0.7`
- Gemini: Uses model default

**Problem:** Document organization benefits from lower temperature (more deterministic) for consistent results.

**Recommendation:** Make temperature configurable per provider:

```python
@dataclass
class ProviderConfig:
    name: str
    provider_type: str
    model: str
    endpoint: str | None = None
    is_active: bool = False
    temperature: float = 0.3  # Lower default for determinism
```

---

### 3.3 No Token Counting or Cost Estimation

**Issue:** No visibility into prompt size or estimated cost before sending.

**Impact:**
- Users can't optimize for cost
- Unexpected large bills
- No warning for prompts approaching context limit

**Recommendation:** Add token estimation:

```python
def estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 characters."""
    return len(text) // 4

# In plan command
total_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
if total_tokens > 10000:
    click.secho(f"Warning: Large prompt ({total_tokens:,} estimated tokens)", fg="yellow")
```

For accurate counting, use provider-specific tokenizers (tiktoken for OpenAI).

---

## 4. Prompt Structure Improvements

### 4.1 Guidelines Priority Not Machine-Readable

**Location:** `src/docman/prompt_templates/system_prompt.j2`

**Issue:** Guidelines are listed "in priority order" but only as numbered list:

```
## Critical Guidelines (in priority order)

1. **Follow organization instructions exactly**
2. **Match existing values when applicable**
...
```

**Problem:** The LLM may not weight priorities correctly based on list position alone.

**Recommendation:** Make priority explicit:

```
## Critical Guidelines

[PRIORITY: HIGHEST] **Follow organization instructions exactly**
[PRIORITY: HIGH] **Match existing values when applicable**
[PRIORITY: MEDIUM] **Preserve file extensions**
...
```

Or use a structured format:

```
## Critical Guidelines

| Priority | Guideline |
|----------|-----------|
| 1 (Must) | Follow organization instructions exactly |
| 2 (Must) | Match existing values when applicable |
| 3 (Should) | Preserve file extensions |
```

---

### 4.2 No Examples in System Prompt

**Issue:** The system prompt describes the task but provides no examples of correct input/output.

**Problem:** Examples are highly effective for LLM task comprehension.

**Recommendation:** Add a few-shot example section:

```jinja2
## Example

Input file: inbox/2024-01-15-invoice.pdf
Content: (begins) "INVOICE\\nFrom: Acme Corp\\nDate: January 15, 2024\\nAmount: $1,500..."

Correct output:
{
    "suggested_directory_path": "Financial/invoices/2024",
    "suggested_filename": "acme-corp-invoice-2024-01.pdf",
    "reason": "Invoice from Acme Corp dated January 2024, filed under Financial/invoices organized by year."
}
```

---

### 4.3 Reason Field Instructions Too Vague

**Issue:** Reason format guidance is minimal:

```
- **Reason format**: 1-2 sentences explaining: (a) document type identified, (b) key metadata extracted, (c) why this location is appropriate
```

**Problem:** LLM reasons are often either too brief or too verbose.

**Recommendation:** Provide clearer structure:

```
- **Reason format**: Exactly 2-3 sentences following this pattern:
  1. State the document type (e.g., "This is an invoice from...")
  2. List extracted metadata (e.g., "Dated January 2024, amount $1,500")
  3. Explain folder choice (e.g., "Filed under invoices/2024 per organization structure")
```

---

## 5. Error Handling Improvements

### 5.1 Generic Exception Messages

**Location:** `src/docman/llm_providers.py`

**Issue:** Error classification converts specific errors to generic messages:

```python
if "api key" in error_msg.lower():
    raise Exception("Invalid API key...")
```

**Problem:** Lost error details make debugging difficult.

**Recommendation:** Use custom exception classes with preserved context:

```python
class LLMProviderError(Exception):
    def __init__(self, message: str, error_type: str, original_error: Exception = None):
        super().__init__(message)
        self.error_type = error_type
        self.original_error = original_error
        self.retryable = error_type in ("rate_limit", "timeout", "connection")

class InvalidAPIKeyError(LLMProviderError):
    def __init__(self, original_error: Exception = None):
        super().__init__(
            "Invalid API key - check your credentials",
            "auth",
            original_error
        )
```

---

### 5.2 No Graceful Degradation

**Issue:** When structured output fails (e.g., API change), there's no fallback.

**Recommendation:** Fall back to prompt-based JSON if structured output fails:

```python
def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict:
    try:
        # Try structured output first
        return self._generate_with_schema(system_prompt, user_prompt)
    except StructuredOutputError:
        # Fall back to prompt-guided JSON
        return self._generate_with_prompt_guidance(system_prompt, user_prompt)
```

---

## 6. Conversation History Management

### 6.1 Process Action Has No History Limit

**Location:** `src/docman/cli.py` (lines 2117-2119)

**Issue:** Each Process action appends to the prompt without limit:

```python
current_user_prompt += "\n\n" + _format_suggestion_as_json(current_suggestion)
current_user_prompt += f"\n\n<userFeedback>\n{user_feedback}\n</userFeedback>"
```

**Problem:** Multiple iterations cause prompt to exceed context window.

**Recommendation:** Implement sliding window for conversation history:

```python
MAX_HISTORY_TURNS = 3

def build_conversation_prompt(
    base_prompt: str,
    history: list[dict],  # [{"suggestion": ..., "feedback": ...}, ...]
) -> str:
    # Keep only last N turns
    recent_history = history[-MAX_HISTORY_TURNS:]

    prompt = base_prompt
    for turn in recent_history:
        prompt += f"\n\n<previousSuggestion>\n{json.dumps(turn['suggestion'])}\n</previousSuggestion>"
        prompt += f"\n\n<userFeedback>\n{turn['feedback']}\n</userFeedback>"

    return prompt
```

---

## 7. Content Analysis Enhancements

### 7.1 No Document Type Pre-Classification

**Issue:** All documents receive the same prompt regardless of type.

**Opportunity:** Different document types have different organization patterns:
- Invoices: Focus on dates, amounts, vendors
- Contracts: Focus on parties, dates, terms
- Reports: Focus on titles, authors, dates
- Correspondence: Focus on sender, recipient, date

**Recommendation:** Add document type hints to prompt:

```python
DOCUMENT_TYPE_HINTS = {
    ".pdf": "May be any document type - analyze content",
    ".docx": "Word document - likely report, letter, or contract",
    ".txt": "Plain text - may be notes or extracted content",
    ".xlsx": "Excel spreadsheet - likely data or financial records",
}

def build_user_prompt(..., file_extension: str = None):
    type_hint = DOCUMENT_TYPE_HINTS.get(file_extension, "")
    # Include in prompt...
```

---

### 7.2 No Metadata Extraction Hints

**Issue:** The LLM must infer where to find dates, names, amounts, etc.

**Recommendation:** Add extraction hints for common metadata:

```
## Metadata Extraction Tips

- **Dates**: Check document header, footer, or first paragraph. Look for formats like "January 15, 2024" or "2024-01-15"
- **Company names**: Often in letterhead, header, or "From:" fields
- **Document numbers**: Look for "Invoice #", "Contract No.", "Reference:"
- **Amounts**: For financial documents, check for "$", "Total:", "Amount Due:"
```

---

## 8. Testing Improvements

### 8.1 Missing Tests for `_extract_filename_patterns()`

**Location:** `src/docman/prompt_builder.py`

**Issue:** This helper function has zero test coverage.

**Recommendation:** Add unit tests:

```python
class TestExtractFilenamePatterns:
    def test_no_conventions_returns_empty(self):
        folders = {"docs": FolderDefinition()}
        result = _extract_filename_patterns(folders)
        assert result == {}

    def test_extracts_folder_specific_convention(self):
        folders = {
            "invoices": FolderDefinition(
                filename_convention="{company}-invoice-{date}"
            )
        }
        result = _extract_filename_patterns(folders)
        assert result == {"invoices": "{company}-invoice-{date}"}

    def test_includes_default_convention(self):
        folders = {"docs": FolderDefinition()}
        result = _extract_filename_patterns(folders, default_convention="{date}-{desc}")
        assert "__default__" in result
```

---

### 8.2 No Integration Tests for Provider Fallback

**Issue:** No tests verify behavior when providers fail or return unexpected responses.

**Recommendation:** Add integration tests with mock failures:

```python
def test_plan_handles_provider_timeout():
    mock_provider.generate_suggestions.side_effect = TimeoutError("Connection timed out")
    result = runner.invoke(cli, ["plan"])
    assert "timed out" in result.output.lower()

def test_plan_handles_malformed_response():
    mock_provider.generate_suggestions.return_value = {"invalid": "response"}
    result = runner.invoke(cli, ["plan"])
    assert "validation failed" in result.output.lower()
```

---

## Priority Implementation Order

1. **Caching improvements (1.1, 1.2)** - Immediate performance gain
2. **Temperature configuration (3.2)** - Easy win for quality
3. **Existing values limit (2.1)** - Reduces duplicate creation
4. **Error handling (5.1, 5.2)** - Better debugging and reliability
5. **Conversation history limit (6.1)** - Prevents context overflow
6. **Pattern name inference (2.2)** - Better defaults
7. **Prompt structure improvements (4.1-4.3)** - Quality enhancement
8. **Testing improvements (8.1, 8.2)** - Stability

---

## Summary

Medium-priority improvements focus on:
- **Performance optimization** through caching and token management
- **Quality enhancement** through better variable handling and prompt structure
- **Reliability** through improved error handling and conversation management
- **Testing** to ensure stability of existing features

These improvements build incrementally on the high-priority foundation and provide measurable gains in LLM response quality and system performance.
