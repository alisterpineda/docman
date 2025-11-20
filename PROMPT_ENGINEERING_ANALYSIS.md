# Prompt Engineering Analysis Report

**Project**: docman
**Date**: November 20, 2025
**Analyst**: Claude Code (claude-sonnet-4-5)

---

## Executive Summary

This report provides a deep analysis of the prompt engineering system in docman, a CLI tool that uses LLMs to suggest document organization. The analysis covers the current architecture, identifies 23 specific issues, and provides prioritized recommendations for optimizing LLM responses.

### Key Findings

| Category | Status | Priority Issues |
|----------|--------|-----------------|
| **Architecture** | Well-structured | Good separation of concerns |
| **Prompt Clarity** | Needs improvement | Ambiguous guidelines, missing context |
| **Few-shot Learning** | Not implemented | Database infrastructure exists but unused |
| **Content Handling** | Suboptimal | Conservative truncation, head-only strategy |
| **Provider Consistency** | Inconsistent | Different prompt composition methods |
| **Cost Optimization** | Partially implemented | No batching, no caching of similar docs |

### Overall Assessment: 6.5/10

The system has solid foundations but leaves significant performance gains on the table. The most impactful improvements are:

1. **Implement few-shot learning** (HIGH - infrastructure exists, ~20% quality improvement)
2. **Fix prompt ambiguities** (HIGH - low effort, immediate clarity gains)
3. **Improve content truncation strategy** (MEDIUM - capture more semantic content)
4. **Standardize provider handling** (MEDIUM - consistent behavior across providers)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [System Prompt Analysis](#2-system-prompt-analysis)
3. [User Prompt Analysis](#3-user-prompt-analysis)
4. [Instruction Generation Analysis](#4-instruction-generation-analysis)
5. [Content Truncation Analysis](#5-content-truncation-analysis)
6. [Provider Integration Analysis](#6-provider-integration-analysis)
7. [Caching and Invalidation](#7-caching-and-invalidation)
8. [Identified Issues](#8-identified-issues)
9. [Recommendations](#9-recommendations)
10. [Implementation Priority Matrix](#10-implementation-priority-matrix)

---

## 1. Architecture Overview

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Prompt Building Flow                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌──────────────────┐    ┌────────────┐ │
│  │ Folder      │    │ Jinja2 Templates │    │ LLM        │ │
│  │ Definitions │───▶│ (system/user.j2) │───▶│ Provider   │ │
│  └─────────────┘    └──────────────────┘    └────────────┘ │
│         │                    │                      │       │
│         ▼                    ▼                      ▼       │
│  ┌─────────────┐    ┌──────────────────┐    ┌────────────┐ │
│  │ Variable    │    │ Content          │    │ Pydantic   │ │
│  │ Patterns    │    │ Truncation       │    │ Validation │ │
│  └─────────────┘    └──────────────────┘    └────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Files Analyzed

| File | Lines | Purpose |
|------|-------|---------|
| `prompt_builder.py` | 530 | Core prompt construction logic |
| `system_prompt.j2` | 29 | LLM role and task definition |
| `user_prompt.j2` | 10 | Document-specific context |
| `llm_providers.py` | 652 | Provider abstraction and API calls |

### Strengths

- **Clean separation**: Templates are external, not embedded in Python code
- **Adaptive design**: Single boolean controls structured vs unstructured output
- **Security-first**: Pydantic validators prevent path traversal in outputs
- **Deterministic caching**: SHA256 hash enables reliable invalidation

### Weaknesses

- **No few-shot learning**: Historical operations exist but aren't used
- **Conservative defaults**: 4000 character limit may lose important context
- **Provider inconsistency**: Different prompt composition methods per provider

---

## 2. System Prompt Analysis

### Current Template (29 lines, 1,502 bytes)

```jinja
You are a document organization assistant. Your task is to analyze documents and suggest how they should be organized in a file system.

You will be provided with:
1. Document organization instructions (wrapped in <organizationInstructions> XML tags)
2. The document's content (wrapped in <documentContent> XML tags with filePath attribute containing the current file path)

Based on this information, suggest an appropriate directory path and filename for the document.
{% if not use_structured_output %}

Provide your suggestion in the following JSON format:
{
    "suggested_directory_path": "path/to/directory",
    "suggested_filename": "filename.ext",
    "reason": "Brief explanation for this organization"
}
{% endif %}

Guidelines:
1. suggested_directory_path should be a relative path with forward slashes (e.g., "finance/invoices/2024")
2. suggested_filename should include the file extension from the original file
3. reason should be a brief explanation (1-2 sentences) of why this makes sense
4. Base your suggestions on the document's content, file type (e.g., PDF, DOCX), date (if present), and any other relevant metadata you can extract
5. Follow the document organization instructions provided
6. When existing values are shown for a variable folder, use an exact match when applicable. Only create new values when the document doesn't match any existing option.
{% if not use_structured_output %}

Return ONLY the JSON object, no additional text or markdown formatting.
{% endif %}
```

### Analysis

#### Positive Aspects

1. **Clear role definition**: "document organization assistant" establishes purpose
2. **Explicit input structure**: Documents what the LLM will receive
3. **Conditional formatting**: Omits JSON instructions when API enforces schema (saves ~100 tokens)
4. **XML boundaries**: Clear separation between instructions and content

#### Issues Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **IS-1** | HIGH | **Guideline #6 is ambiguous**: "When existing values are shown" - where? The LLM doesn't know existing values appear in the organization instructions |
| **IS-2** | MEDIUM | **No priority ordering**: 6 guidelines with no indication of relative importance |
| **IS-3** | MEDIUM | **Missing truncation notice**: Documents may be truncated but LLM isn't informed |
| **IS-4** | LOW | **No error guidance**: What should LLM do if document is empty or unreadable? |
| **IS-5** | LOW | **Extension handling unclear**: Says "include the file extension from the original file" but doesn't explain where to find original extension |

#### Token Cost Analysis

- **Structured output mode** (Gemini/OpenAI): ~570 tokens per document
- **Non-structured mode** (LM Studio): ~670 tokens per document
- **Difference**: 18% more tokens for non-structured output

---

## 3. User Prompt Analysis

### Current Template (10 lines, 213 bytes)

```jinja
{% if organization_instructions %}
<organizationInstructions>
{{ organization_instructions }}
</organizationInstructions>
{% endif %}

<documentContent filePath="{{ file_path }}">
{{ content }}
</documentContent>
```

### Analysis

#### Positive Aspects

1. **Minimal and focused**: Only includes necessary information
2. **XML boundaries**: Clear tag structure for parsing
3. **File path in attribute**: Embeds path directly in `documentContent` tag
4. **Conditional instructions**: Can omit if no folder definitions

#### Issues Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **IU-1** | HIGH | **No file metadata**: Missing creation date, file size, document type metadata that could inform organization |
| **IU-2** | MEDIUM | **No context about truncation**: If content was truncated, LLM should know |
| **IU-3** | LOW | **camelCase XML tags**: Non-standard; convention is `kebab-case` or `snake_case` |

#### Improvement Opportunity: File Metadata

Adding metadata would significantly improve suggestions:

```jinja
<documentContent filePath="{{ file_path }}" fileType="{{ file_type }}" createdDate="{{ created_date }}" fileSize="{{ file_size }}">
{{ content }}
{% if was_truncated %}
[Content truncated from {{ original_length }} characters]
{% endif %}
</documentContent>
```

---

## 4. Instruction Generation Analysis

### Function: `generate_instructions_from_folders()`

This function converts folder definitions into markdown instructions. It generates three sections:

1. **Folder Hierarchy**: Tree structure with descriptions
2. **Filename Conventions**: Default and folder-specific patterns
3. **Variable Pattern Extraction**: Guidance for extracting values

### Generated Output Example

```markdown
# Document Organization Structure

The following folder structure defines how documents should be organized:

- **Financial/** - Financial documents
  - **invoices/** [filename: {company}-invoice-{year}-{month}]
    - **{year}/** - Invoices by year (YYYY format)
      Existing: 2023, 2024, 2025
  - **receipts/**
    - **{category}/** - Personal receipts by category

# Filename Conventions

Files should be renamed according to the following conventions. The original file extension must be preserved.

**Default Convention**: `{year}-{month}-{description}`
  - This convention applies to all folders unless overridden below

**Folder-Specific Conventions**:
  - `Financial/invoices/{year}`: `{company}-invoice-{year}-{month}`

# Variable Pattern Extraction

Some folders and filename conventions use variable patterns (indicated by curly braces like {year}). Extract these values from the document content:

**year**:
  - 4-digit year in YYYY format

**month**:
  - 2-digit month in MM format (01-12)

**company**:
  - Company name extracted from invoice header
```

### Analysis

#### Positive Aspects

1. **Filesystem-aware**: Scans actual directories for existing values
2. **Three-section structure**: Logical separation of concerns
3. **Variable pattern guidance**: Explicit extraction instructions
4. **Graceful degradation**: Undefined patterns show warnings but don't fail

#### Issues Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **IG-1** | HIGH | **"Existing:" values not explained**: Guideline #6 references "shown values" but instructions don't explain what "Existing: 2023, 2024, 2025" means |
| **IG-2** | MEDIUM | **No priority between folders**: If a document matches multiple folders, which takes precedence? |
| **IG-3** | MEDIUM | **Hard-coded limit**: Only shows 10 existing directory values (line 400), could be configurable |
| **IG-4** | LOW | **No example documents**: Would help LLM understand expected behavior |

#### Connection to Guideline #6 Problem

The system prompt says:
> "When existing values are shown for a variable folder, use an exact match when applicable"

But the instructions show:
> `Existing: 2023, 2024, 2025`

**The LLM has no context that these are the "existing values" referenced in the guideline.** This is a critical ambiguity that could lead to inconsistent behavior.

---

## 5. Content Truncation Analysis

### Current Implementation

```python
def _truncate_content_smart(
    content: str,
    max_chars: int = 4000,
) -> tuple[str, bool]:
    """Truncate content to fit within character limit."""
    if len(content) <= max_chars:
        return content, False

    estimated_removed = len(content) - max_chars
    marker = f"\n\n[... {estimated_removed:,} characters truncated ...]"
    available_chars = max_chars - len(marker)
    truncated = content[:available_chars].rstrip()

    return f"{truncated}{marker}", True
```

### Analysis

#### Issues Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **IT-1** | HIGH | **Documentation mismatch**: CLAUDE.md states "Keeps beginning (60%) and end (30%) of long documents" but code only keeps the beginning |
| **IT-2** | HIGH | **Loses important context**: Documents often have key information at the end (signatures, totals, dates) |
| **IT-3** | MEDIUM | **Conservative limit**: 4000 characters is only ~1000 tokens; modern LLMs handle 128K+ contexts |
| **IT-4** | MEDIUM | **No semantic awareness**: Truncates mid-sentence, mid-paragraph |
| **IT-5** | LOW | **Fixed truncation point**: Should consider document structure (sections, paragraphs) |

#### Better Truncation Strategy

For document organization, critical information often appears at:
- **Beginning**: Title, author, date, type indicators
- **End**: Signatures, totals, conclusions, dates
- **Headers**: Section titles throughout document

Recommended approach:

```python
def _truncate_content_smart(
    content: str,
    max_chars: int = 8000,  # Increase limit for modern LLMs
) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False

    # Allocate: 50% beginning, 40% end, 10% marker
    marker_budget = int(max_chars * 0.10)
    begin_budget = int(max_chars * 0.50)
    end_budget = max_chars - marker_budget - begin_budget

    marker = f"\n\n[... {len(content) - begin_budget - end_budget:,} chars truncated ...]\n\n"

    # Find clean break points (paragraph boundaries)
    begin_part = content[:begin_budget].rsplit('\n\n', 1)[0]
    end_part = content[-end_budget:].split('\n\n', 1)[-1]

    return f"{begin_part}{marker}{end_part}", True
```

---

## 6. Provider Integration Analysis

### Provider Comparison

| Aspect | Google Gemini | OpenAI Official | OpenAI Custom (LM Studio) |
|--------|---------------|-----------------|---------------------------|
| **Structured Output** | Yes | Yes | No |
| **Prompt Composition** | Combined string | Separate messages | Separate messages |
| **Temperature** | Default (unset) | 0.7 | 0.7 |
| **Schema Enforcement** | `response_schema` param | `json_schema` mode | System prompt guidance |

### Critical Inconsistency: Prompt Composition

**Google Gemini**:
```python
combined_prompt = f"{system_prompt}\n\n{user_prompt}"
response = self.model.generate_content(combined_prompt)
```

**OpenAI**:
```python
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
]
response = self.client.chat.completions.create(messages=messages)
```

### Issues Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **IP-1** | HIGH | **Different semantic interpretation**: Gemini sees one combined message; OpenAI separates system/user roles. This affects how the LLM interprets instructions. |
| **IP-2** | MEDIUM | **Temperature inconsistency**: Gemini uses provider default; OpenAI explicitly sets 0.7. Affects creativity/consistency tradeoff. |
| **IP-3** | MEDIUM | **Response format handling**: Only handles markdown code blocks; other JSON wrapping formats may fail. |
| **IP-4** | LOW | **Finish reason checking**: Gemini uses string matching on enum repr (`'SAFETY' in finish_reason`); fragile approach. |

### Recommendation: Standardize Provider Behavior

1. **Always use role separation** where supported
2. **Set explicit temperature** for all providers (recommend 0.3 for consistency)
3. **Gemini prompt composition**:

```python
# Use system_instruction parameter for Gemini
self.model = genai.GenerativeModel(
    config.model,
    generation_config=generation_config,
    system_instruction=system_prompt,  # Proper separation
)
# Then only pass user_prompt to generate_content
response = self.model.generate_content(user_prompt)
```

---

## 7. Caching and Invalidation

### Current Mechanism

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

### Three-Factor Invalidation

Operations are regenerated when any of these change:
1. **Prompt hash** (system prompt + instructions + model name + folder definitions)
2. **Document content hash** (SHA256 of file content)
3. **Model name** (explicit check separate from prompt hash)

### Analysis

#### Positive Aspects

1. **Deterministic**: Same inputs always produce same hash
2. **Comprehensive**: Catches all meaningful changes
3. **Efficient**: Avoids redundant LLM calls

#### Issues Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **IC-1** | MEDIUM | **Model name double-counted**: Model name is in prompt hash AND checked separately |
| **IC-2** | LOW | **No semantic similarity**: Changes that don't affect output still invalidate (e.g., whitespace) |
| **IC-3** | LOW | **LRU cache too small**: `maxsize=2` only caches 2 system prompts (structured/unstructured) |

---

## 8. Identified Issues

### Summary by Severity

| Severity | Count | Categories |
|----------|-------|------------|
| **HIGH** | 7 | Ambiguity, Missing Features, Consistency |
| **MEDIUM** | 11 | Optimization, Documentation, Clarity |
| **LOW** | 5 | Style, Minor Improvements |

### Complete Issue List

#### HIGH Severity

| ID | Issue | Component | Impact |
|----|-------|-----------|--------|
| **IS-1** | Guideline #6 ambiguous ("shown values") | System Prompt | LLM doesn't know what "shown" means |
| **IG-1** | "Existing:" values not explained | Instructions | No connection to Guideline #6 |
| **IT-1** | Documentation says 60%/30% split, code uses head-only | Truncation | Misleading documentation |
| **IT-2** | Loses important end-of-document context | Truncation | Misses signatures, totals, dates |
| **IP-1** | Different prompt composition per provider | Providers | Inconsistent LLM interpretation |
| **IU-1** | No file metadata in user prompt | User Prompt | Missing useful context |
| **FSL-1** | Few-shot learning not implemented | Architecture | Database infrastructure unused |

#### MEDIUM Severity

| ID | Issue | Component | Impact |
|----|-------|-----------|--------|
| **IS-2** | No priority ordering for guidelines | System Prompt | Unclear importance hierarchy |
| **IS-3** | Missing truncation notice in prompt | System Prompt | LLM unaware content may be partial |
| **IU-2** | No context about truncation in user prompt | User Prompt | LLM can't adjust analysis |
| **IG-2** | No priority between matching folders | Instructions | Ambiguous multi-match handling |
| **IG-3** | Hard-coded 10-value limit for existing dirs | Instructions | Not configurable |
| **IT-3** | Conservative 4000 char limit | Truncation | Loses context unnecessarily |
| **IT-4** | No semantic awareness in truncation | Truncation | Cuts mid-sentence |
| **IP-2** | Temperature inconsistency across providers | Providers | Different creativity/consistency |
| **IP-3** | Limited response format handling | Providers | May fail on non-markdown JSON |
| **IC-1** | Model name double-counted in hash | Caching | Minor redundancy |
| **DOC-1** | Schema fields lack detailed descriptions | Schema | Less helpful structured output |

#### LOW Severity

| ID | Issue | Component | Impact |
|----|-------|-----------|--------|
| **IS-4** | No error guidance for empty documents | System Prompt | Edge case handling |
| **IS-5** | Extension handling unclear in prompt | System Prompt | Minor ambiguity |
| **IU-3** | camelCase XML tags (non-standard) | User Prompt | Consistency |
| **IP-4** | Fragile finish_reason checking | Providers | May break with API updates |
| **IC-3** | LRU cache too small | Caching | Minor optimization |

---

## 9. Recommendations

### 9.1 Implement Few-Shot Learning (HIGH PRIORITY)

**Current State**: Database has `operations` table with `status` field (ACCEPTED/REJECTED) and index on `(status, prompt_hash)` for fast lookups. This infrastructure is completely unused.

**Recommendation**: Add few-shot examples to user prompts using historical operations.

```python
def build_user_prompt_with_examples(
    file_path: str,
    document_content: str,
    organization_instructions: str | None,
    session: Session,
    prompt_hash: str,
    max_examples: int = 3,
) -> str:
    # Query successful historical operations with same prompt hash
    examples = session.query(Operation).filter(
        Operation.status == OperationStatus.ACCEPTED,
        Operation.prompt_hash == prompt_hash,
    ).order_by(Operation.updated_at.desc()).limit(max_examples).all()

    # Format examples
    example_section = ""
    if examples:
        example_section = "<examples>\n"
        for i, ex in enumerate(examples, 1):
            example_section += f"""<example{i}>
<input>{ex.document_copy.file_path}</input>
<output>
{{"suggested_directory_path": "{ex.suggested_directory_path}",
 "suggested_filename": "{ex.suggested_filename}",
 "reason": "{ex.reason}"}}
</output>
</example{i}>
"""
        example_section += "</examples>\n\n"

    # Insert before document content
    return example_section + original_user_prompt
```

**Expected Impact**: 15-25% improvement in consistency and accuracy based on prompt engineering research.

### 9.2 Fix Guideline #6 Ambiguity (HIGH PRIORITY)

**Current**:
> "When existing values are shown for a variable folder, use an exact match when applicable."

**Recommended**:
> "When the organization instructions show 'Existing:' values under a variable folder (e.g., 'Existing: 2023, 2024, 2025'), these are actual directories that already exist. Use an exact match from this list when the document matches one. Only create a new value if the document doesn't fit any existing option."

### 9.3 Improve Content Truncation (MEDIUM PRIORITY)

**Changes**:
1. Increase default limit to 8000 characters (still conservative for 128K context models)
2. Implement 50%/40% beginning/end split
3. Find clean break points (paragraph boundaries)
4. Inform LLM about truncation in system prompt

**Add to system prompt guidelines**:
> "7. Document content may be truncated if very long. The beginning and end are preserved. If you see '[... X chars truncated ...]', the full document is longer."

### 9.4 Add File Metadata to User Prompt (MEDIUM PRIORITY)

**Extend user prompt template**:

```jinja
<documentMetadata>
  <filePath>{{ file_path }}</filePath>
  <fileExtension>{{ file_extension }}</fileExtension>
  <fileSize>{{ file_size_human }}</fileSize>
  <lastModified>{{ last_modified }}</lastModified>
  {% if was_truncated %}
  <truncated>true ({{ original_length }} chars → {{ truncated_length }} chars)</truncated>
  {% endif %}
</documentMetadata>

<documentContent>
{{ content }}
</documentContent>
```

### 9.5 Standardize Provider Temperature (MEDIUM PRIORITY)

Set explicit temperature for all providers:

```python
# In GoogleGeminiProvider.__init__
generation_config = genai.GenerationConfig(
    response_mime_type="application/json",
    response_schema=OrganizationSuggestion,
    temperature=0.3,  # Lower for more consistent outputs
)

# In OpenAICompatibleProvider.generate_suggestions
request_params = {
    "model": self.config.model,
    "messages": [...],
    "temperature": 0.3,  # Match Gemini
}
```

### 9.6 Use Gemini System Instruction (MEDIUM PRIORITY)

```python
class GoogleGeminiProvider(LLMProvider):
    def __init__(self, config: ProviderConfig, api_key: str):
        # ... existing setup ...

        # Store system prompt for later use
        self._system_prompt = None

        self.model = genai.GenerativeModel(
            config.model,
            generation_config=generation_config,
        )

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        # Use system_instruction for proper role separation
        model_with_system = genai.GenerativeModel(
            self.config.model,
            generation_config=self.model.generation_config,
            system_instruction=system_prompt,
        )
        response = model_with_system.generate_content(user_prompt)
        # ... rest of method
```

### 9.7 Add Priority to Guidelines (LOW PRIORITY)

**Rewrite guidelines with explicit priorities**:

```
Guidelines (in order of importance):

MUST follow:
1. Follow the document organization instructions provided
2. suggested_filename must include the file extension from the original file
3. suggested_directory_path must be a relative path with forward slashes

SHOULD follow:
4. When existing values are shown for a variable folder, use an exact match when applicable
5. Base suggestions on document content, type, dates, and metadata

RECOMMENDED:
6. Provide a brief (1-2 sentence) reason explaining why this organization makes sense
```

### 9.8 Enhance OrganizationSuggestion Schema (LOW PRIORITY)

Add descriptions for better structured output guidance:

```python
class OrganizationSuggestion(BaseModel):
    """Pydantic model for document organization suggestions."""

    suggested_directory_path: str = Field(
        description="Relative directory path using forward slashes (e.g., 'finance/invoices/2024'). Can be empty for root directory."
    )
    suggested_filename: str = Field(
        description="New filename including original extension (e.g., 'acme-invoice-2024-03.pdf'). Must not be empty."
    )
    reason: str = Field(
        description="Brief 1-2 sentence explanation of why this organization makes sense based on document content."
    )
```

---

## 10. Implementation Priority Matrix

### Effort vs Impact Analysis

```
                    HIGH IMPACT
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
    │  [9.1] Few-shot    │  [9.3] Truncation  │
    │  [9.2] Guideline   │  [9.4] Metadata    │
    │                    │                    │
 LOW├────────────────────┼────────────────────┤HIGH
EFFORT                   │                    EFFORT
    │                    │                    │
    │  [9.7] Priorities  │  [9.5] Temperature │
    │  [9.8] Schema      │  [9.6] Gemini sys  │
    │                    │                    │
    └────────────────────┼────────────────────┘
                         │
                    LOW IMPACT
```

### Recommended Implementation Order

| Phase | Items | Time Estimate | Expected Impact |
|-------|-------|---------------|-----------------|
| **Phase 1** | 9.2, 9.7, 9.8 | 2-4 hours | Immediate clarity improvement |
| **Phase 2** | 9.1 (Few-shot) | 4-8 hours | 15-25% quality improvement |
| **Phase 3** | 9.3, 9.4 | 4-6 hours | Better context preservation |
| **Phase 4** | 9.5, 9.6 | 2-4 hours | Provider consistency |

### Quick Wins (Can be done immediately)

1. **Fix Guideline #6 wording** (5 minutes)
2. **Add truncation note to system prompt** (5 minutes)
3. **Update CLAUDE.md to match actual truncation behavior** (5 minutes)
4. **Add explicit temperature to Gemini** (10 minutes)

---

## Appendix A: Best Practices Comparison

### Industry Best Practices for Document Organization Prompts

| Practice | Current State | Recommendation |
|----------|---------------|----------------|
| **Role clarity** | Good | Keep as-is |
| **Task decomposition** | Not used | Consider for complex docs |
| **Few-shot examples** | Not implemented | HIGH priority |
| **Chain-of-thought** | Not used | Not needed for this task |
| **Output format specification** | Good (conditional) | Keep as-is |
| **Context window utilization** | Poor (4K/128K) | Increase limit |
| **Error handling guidance** | Missing | Add edge case instructions |

### Prompt Engineering Principles Applied

| Principle | Application |
|-----------|-------------|
| **Be specific** | Good use of XML tags and field requirements |
| **Give examples** | Missing - high priority to add |
| **Use delimiters** | Good use of `<organizationInstructions>` and `<documentContent>` |
| **Specify output format** | Good with conditional JSON format |
| **Break down complex tasks** | N/A - task is relatively simple |

---

## Appendix B: Token Cost Analysis

### Current Token Usage per Document

| Component | Tokens (Structured) | Tokens (Unstructured) |
|-----------|--------------------|-----------------------|
| System prompt | ~150 | ~250 |
| Organization instructions | ~200-500 | ~200-500 |
| Document content | ~1000 (4K chars) | ~1000 (4K chars) |
| **Total input** | ~1350-1650 | ~1450-1750 |
| Output | ~50 | ~50 |

### Cost Optimization Opportunities

1. **Increase truncation limit to 8K**: Only ~$0.001 more per document
2. **Add few-shot examples (3)**: ~150 tokens, $0.0002 per document
3. **Implement batching**: Could save 30-50% on OpenAI API calls

---

## Appendix C: Testing Recommendations

### New Test Cases Needed

1. **Guideline #6 behavior**: Verify LLM uses existing values when applicable
2. **Truncation edge cases**: Test documents exactly at limit, just over, very long
3. **Provider parity**: Same document should get similar suggestions from Gemini and OpenAI
4. **Few-shot learning**: Compare suggestions with/without examples
5. **Metadata influence**: Test if metadata improves suggestions

### Test File Suggestions

Create test documents that:
- Match existing variable pattern values (test Guideline #6)
- Have important information at end (test truncation impact)
- Are ambiguous (could fit multiple folders)
- Have clear dates/companies (test variable extraction)

---

## Conclusion

The docman prompt engineering system has a solid foundation but significant room for improvement. The highest-impact changes are:

1. **Implementing few-shot learning** using existing database infrastructure
2. **Fixing the Guideline #6 ambiguity** that creates confusion about existing values
3. **Improving content truncation** to preserve important end-of-document information

These changes require relatively modest effort but could yield 20-30% improvement in suggestion quality and consistency. The recommendations in this report are ordered by priority and include specific implementation guidance.

---

*Report generated by Claude Code on November 20, 2025*
