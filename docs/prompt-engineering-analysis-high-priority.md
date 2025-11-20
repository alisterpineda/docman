# Prompt Engineering Analysis: High Priority Improvements

**Analysis Date:** 2025-11-20
**Scope:** docman LLM prompt system in `src/docman/prompt_builder.py` and related modules

---

## Executive Summary

This document identifies high-priority improvements for the docman prompt engineering system. These issues affect security, reliability, and LLM response quality and should be addressed first.

---

## 1. Security Vulnerabilities

### 1.1 XML Injection Risk in Document Content

**Location:** `src/docman/prompt_templates/user_prompt.j2`

**Issue:** Document content is inserted directly into XML tags without escaping:

```jinja2
<documentContent filePath="{{ file_path }}">
{{ content }}
</documentContent>
```

If document content contains `</documentContent>` or other XML control sequences, it could break parsing or inject malicious instructions.

**Impact:**
- Potential prompt injection attacks
- Malformed prompts causing LLM errors
- Unpredictable LLM behavior

**Recommendation:** Use CDATA sections to isolate content:

```jinja2
<documentContent filePath="{{ file_path }}">
<![CDATA[
{{ content }}
]]>
</documentContent>
```

Or implement XML escaping for the content variable.

---

### 1.2 File Path Attribute Escaping

**Location:** `src/docman/prompt_templates/user_prompt.j2`

**Issue:** File paths with quotes could break the XML attribute:

```jinja2
filePath="{{ file_path }}"
```

A path like `my "document".pdf` would produce invalid XML: `filePath="my "document".pdf"`.

**Recommendation:**
- Escape quotes in file paths using HTML entities
- Or use Jinja2's `|e` (escape) filter: `{{ file_path|e }}`

---

## 2. Prompt Hash Inconsistency

### 2.1 Unused `compute_prompt_hash()` Function

**Location:** `src/docman/prompt_builder.py` (lines 536-568)

**Issue:** The `compute_prompt_hash()` function exists but is NOT used by the CLI. Instead, the CLI computes hashes inline in two places:
- `plan` command (lines 843-846)
- `_persist_reprocessed_suggestion()` (lines 1643-1646)

**Problems:**
1. **DRY violation:** Same logic duplicated in three places
2. **Maintenance risk:** Changes to hash logic must be synchronized
3. **Inconsistency risk:** Function includes different components than CLI inline code
4. **Testing gap:** Function is never tested because it's never called

**Current inline computation (CLI):**
```python
prompt_components = system_prompt
if organization_instructions:
    prompt_components += "\n" + organization_instructions
if model_name:
    prompt_components += "\n" + model_name
if folder_definitions:
    prompt_components += "\n" + serialize_folder_definitions(
        folder_definitions, default_filename_convention
    )

import hashlib
sha256_hash = hashlib.sha256()
sha256_hash.update(prompt_components.encode("utf-8"))
current_prompt_hash = sha256_hash.hexdigest()
```

**Function definition (unused):**
```python
def compute_prompt_hash(
    system_prompt: str,
    organization_instructions: str | None = None,
    model_name: str | None = None,
) -> str:
    combined = system_prompt
    if organization_instructions:
        combined += "\n" + organization_instructions
    if model_name:
        combined += "\n" + model_name
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
```

Note: The function doesn't include `serialize_folder_definitions()`, creating inconsistency.

**Recommendation:**
1. Update `compute_prompt_hash()` to accept folder definitions parameter
2. Replace all inline hash computations with function calls
3. Add comprehensive unit tests for the function

---

## 3. Missing Structured Output Testing

### 3.1 Conditional Template Logic Untested

**Location:** `src/docman/prompt_templates/system_prompt.j2`

**Issue:** The system prompt template has conditional blocks for structured output:

```jinja2
{% if not use_structured_output %}
Respond with this exact JSON structure:
{
    "suggested_directory_path": "relative/path/to/folder",
    "suggested_filename": "new-filename.ext",
    "reason": "Brief explanation of classification rationale"
}
{% endif %}
```

**Problem:** All tests use the default `use_structured_output=False`. The `True` case (used by Google Gemini and OpenAI official API) is never tested.

**Impact:**
- Template changes could break structured output mode silently
- No verification that JSON format instructions are properly omitted
- Token waste if JSON instructions incorrectly included

**Recommendation:** Add tests for `build_system_prompt(use_structured_output=True)`:

```python
def test_system_prompt_structured_output_excludes_json_format():
    prompt = build_system_prompt(use_structured_output=True)
    assert "Respond with this exact JSON structure" not in prompt
    assert '"suggested_directory_path"' not in prompt
    assert "Return ONLY the JSON object" not in prompt

def test_system_prompt_unstructured_includes_json_format():
    prompt = build_system_prompt(use_structured_output=False)
    assert "Respond with this exact JSON structure" in prompt
    assert '"suggested_directory_path"' in prompt
```

---

## 4. Content Truncation Limitations

### 4.1 Fixed 50/50 Split Not Optimal for All Documents

**Location:** `src/docman/prompt_builder.py` - `_truncate_content_smart()`

**Issue:** The truncation algorithm always splits content 50/50 between beginning and end:

```python
head_chars = available // 2
tail_chars = available - head_chars
```

**Problems:**
- For many document types (invoices, letters, reports), the beginning contains more critical information (headers, dates, parties, titles)
- The ending often contains less important content (signatures, disclaimers, appendices)
- No way to configure the split ratio

**Recommendation:** Make the split ratio configurable:

```python
def _truncate_content_smart(
    content: str,
    max_chars: int = 8000,
    head_ratio: float = 0.6,  # 60% head, 40% tail
) -> tuple[str, bool, int, int]:
    ...
    head_chars = int(available * head_ratio)
    tail_chars = available - head_chars
```

Consider document-type-specific defaults:
- Invoices: 70/30 (headers, amounts at top)
- Contracts: 60/40 (parties, terms at start)
- Reports: 50/50 (introduction and conclusion both important)

---

### 4.2 Hardcoded Truncation Limit

**Issue:** The 8000 character limit is hardcoded without documentation or configurability.

**Problems:**
- Different LLM models have different context windows
- Cost optimization may require different limits
- No way to adjust for specific use cases

**Recommendation:**
1. Make limit configurable via environment variable or config:
   ```python
   DEFAULT_MAX_CHARS = int(os.environ.get("DOCMAN_MAX_CONTENT_CHARS", "8000"))
   ```
2. Document the rationale for the default (e.g., based on typical LLM context windows)
3. Consider per-provider defaults based on model context size

---

### 4.3 Truncation Marker Could Appear in Content

**Issue:** The marker `[... X characters omitted ...]` could theoretically appear in actual document content, causing confusion.

**Recommendation:** Use a more unique marker:

```python
marker = f"\n\n<<<DOCMAN_TRUNCATION: {omitted:,} characters omitted>>>\n\n"
```

---

## 5. JSON Schema Synchronization

### 5.1 Template Schema Not Auto-Generated from Pydantic Model

**Location:** `src/docman/prompt_templates/system_prompt.j2`

**Issue:** When `use_structured_output=False`, the JSON schema is hardcoded in the template:

```jinja2
{
    "suggested_directory_path": "relative/path/to/folder",
    "suggested_filename": "new-filename.ext",
    "reason": "Brief explanation of classification rationale"
}
```

**Problem:** If the `OrganizationSuggestion` Pydantic model changes (e.g., adding a `confidence` field), the template must be manually updated.

**Recommendation:** Generate the schema from the Pydantic model and inject it:

```python
from docman.llm_providers import OrganizationSuggestion

def build_system_prompt(use_structured_output: bool = False) -> str:
    schema_json = None
    if not use_structured_output:
        schema_json = json.dumps(
            OrganizationSuggestion.model_json_schema()["properties"],
            indent=4
        )

    template = _template_env.get_template("system_prompt.j2")
    return template.render(
        use_structured_output=use_structured_output,
        json_schema=schema_json
    )
```

---

## 6. Few-Shot Examples Not Utilized

### 6.1 Historical Operations Exist But Not Used in Prompts

**Issue:** The system stores accepted/rejected operations with `prompt_hash` for "few-shot prompting" (mentioned in CLAUDE.md), but this feature is not implemented.

**Database Design (from CLAUDE.md):**
> **Few-shot index**: Composite index on `(status, prompt_hash)` for fast historical lookup

**Problem:** Without few-shot examples, the LLM has no context of what the user considers good organization suggestions.

**Impact:**
- Repeated mistakes for similar documents
- No learning from user corrections
- Inconsistent suggestions

**Recommendation:** Implement few-shot example injection:

```python
def get_few_shot_examples(
    session: Session,
    prompt_hash: str,
    limit: int = 3
) -> list[dict]:
    """Get recent accepted operations with same prompt hash."""
    operations = session.query(Operation).filter(
        Operation.status == "accepted",
        Operation.prompt_hash == prompt_hash
    ).order_by(Operation.created_at.desc()).limit(limit).all()

    return [
        {
            "input": op.document_copy.file_path,
            "output": {
                "suggested_directory_path": op.suggested_directory_path,
                "suggested_filename": op.suggested_filename,
                "reason": op.reason
            }
        }
        for op in operations
    ]

# In prompt construction:
examples = get_few_shot_examples(session, prompt_hash, limit=3)
if examples:
    organization_instructions += "\n\n## Examples of Correct Classifications\n"
    for ex in examples:
        organization_instructions += f"\nInput: {ex['input']}\n"
        organization_instructions += f"Output: {json.dumps(ex['output'], indent=2)}\n"
```

---

## 7. Process Action Prompt Structure

### 7.1 Growing Prompt Without Clear Boundaries

**Location:** `src/docman/cli.py` (lines 2117-2119)

**Issue:** The Process action (regenerating suggestions with feedback) appends to the user prompt without clear structure:

```python
current_user_prompt += "\n\n" + _format_suggestion_as_json(current_suggestion)
current_user_prompt += f"\n\n<userFeedback>\n{user_feedback}\n</userFeedback>"
```

**Problems:**
1. Prompt grows unbounded with each Process iteration
2. Mix of XML tags (`<userFeedback>`) and raw JSON creates inconsistent structure
3. No clear conversation boundary for the LLM
4. May exceed context window limits

**Recommendation:** Create a dedicated template for conversation-style prompts:

```jinja2
{# conversation_prompt.j2 #}
{% for turn in conversation_history %}
{% if turn.type == "suggestion" %}
<previousSuggestion>
{{ turn.content | tojson }}
</previousSuggestion>
{% elif turn.type == "feedback" %}
<userFeedback>
{{ turn.content }}
</userFeedback>
{% endif %}
{% endfor %}

{% if organization_instructions %}
<organizationInstructions>
{{ organization_instructions }}
</organizationInstructions>
{% endif %}

<documentContent filePath="{{ file_path }}">
{{ content }}
</documentContent>
```

---

## 8. No Retry Logic for LLM Calls

### 8.1 Transient Failures Cause Complete Failure

**Location:** `src/docman/llm_providers.py`

**Issue:** LLM provider calls have no retry logic:

```python
response = self.model.generate_content(combined_prompt)  # Single attempt
```

**Impact:**
- Network timeouts cause failure
- Rate limit errors not handled gracefully
- Transient API errors abort entire operation

**Recommendation:** Implement retry with exponential backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class GoogleGeminiProvider(LLMProvider):
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError))
    )
    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict:
        ...
```

---

## Priority Implementation Order

1. **Security fixes (1.1, 1.2)** - Immediate security concerns
2. **Prompt hash consolidation (2.1)** - Maintenance and consistency
3. **Few-shot examples (6.1)** - Significant quality improvement
4. **Retry logic (8.1)** - Reliability improvement
5. **Structured output testing (3.1)** - Prevent regressions
6. **Content truncation improvements (4.1-4.3)** - Quality enhancement
7. **Schema synchronization (5.1)** - Maintainability
8. **Process action structure (7.1)** - UX improvement

---

## Summary

The high-priority improvements focus on:
- **Security hardening** for XML injection and path escaping
- **Reliability** through retry logic and proper testing
- **Quality** through few-shot examples and better truncation
- **Maintainability** through code consolidation and schema synchronization

Addressing these issues will significantly improve the robustness and effectiveness of the LLM prompt system.
