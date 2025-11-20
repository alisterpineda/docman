# Prompt Engineering Analysis Report

## Executive Summary

This report provides a comprehensive analysis of the prompt engineering system in docman, a CLI tool for AI-powered document organization. The system demonstrates solid architectural foundations but has several opportunities for optimization to improve LLM response quality, reduce costs, and enhance reliability.

**Key Findings:**
- Well-structured modular architecture with good separation of concerns
- Several opportunities for improved prompt clarity and specificity
- Missing few-shot learning despite infrastructure being in place
- Content truncation strategy could be enhanced
- Provider-specific optimizations not fully leveraged

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Strengths](#2-strengths)
3. [Areas for Improvement](#3-areas-for-improvement)
4. [Specific Recommendations](#4-specific-recommendations)
5. [Priority Matrix](#5-priority-matrix)
6. [Implementation Notes](#6-implementation-notes)

---

## 1. Architecture Overview

### Current Prompt Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Folder Defs     │ ──► │ generate_        │ ──► │ Organization    │
│ Variable Pats   │     │ instructions()   │     │ Instructions    │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ system_prompt   │ ──► │ build_system_    │ ──► │ System Prompt   │
│ .j2 template    │     │ prompt()         │     │ (cached)        │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
┌─────────────────┐     ┌──────────────────┐              │
│ Document        │ ──► │ build_user_      │              │
│ Content         │     │ prompt()         │              │
└─────────────────┘     └──────────────────┘              │
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Truncate to     │ ──► │ Render user_     │ ──► │ LLM Provider    │
│ 4000 chars      │     │ prompt.j2        │     │ API Call        │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

### Key Components

| File | Purpose |
|------|---------|
| `prompt_builder.py` | Core prompt construction logic |
| `prompt_templates/system_prompt.j2` | Static task definition |
| `prompt_templates/user_prompt.j2` | Dynamic document presentation |
| `llm_providers.py` | Provider-specific API interactions |

---

## 2. Strengths

### 2.1 Modular Architecture

**Good:** Clear separation between prompt logic, templates, and provider interactions.

```python
# Clean separation of concerns
system_prompt = build_system_prompt(use_structured_output=...)
user_prompt = build_user_prompt(file_path, content, instructions)
result = provider.generate_suggestions(system_prompt, user_prompt)
```

### 2.2 Provider Capability Adaptation

**Good:** Prompts adapt based on `supports_structured_output` property.

```jinja2
{% if not use_structured_output %}
Provide your suggestion in the following JSON format:
{...}
{% endif %}
```

This prevents redundant instructions when the API enforces schema.

### 2.3 XML Boundary Tags

**Good:** Clear demarcation between instructions and content using XML tags.

```xml
<organizationInstructions>
...
</organizationInstructions>

<documentContent filePath="...">
...
</documentContent>
```

This reduces ambiguity about where user data begins/ends.

### 2.4 Security Validation

**Good:** Pydantic validators prevent path traversal attacks on LLM outputs.

```python
@field_validator("suggested_directory_path")
def validate_directory_path(cls, v: str) -> str:
    validate_path_component(v, allow_empty=True)
    return v
```

### 2.5 Deterministic Hashing for Invalidation

**Good:** SHA256 hash computation enables efficient cache invalidation.

```python
def compute_prompt_hash(system_prompt, organization_instructions, model_name):
    combined = system_prompt
    if organization_instructions:
        combined += "\n" + organization_instructions
    if model_name:
        combined += "\n" + model_name
    return hashlib.sha256(combined.encode()).hexdigest()
```

### 2.6 Existing Directory Detection

**Good:** Showing existing values helps LLMs make consistent choices.

```markdown
- **invoices/** - Invoices by year
  Existing: 2020, 2021, 2022, 2023, 2024
```

---

## 3. Areas for Improvement

### 3.1 System Prompt Lacks Role Specificity

**Issue:** The current system prompt is generic and lacks domain expertise framing.

**Current:**
```
You are a document organization assistant.
```

**Problem:** Modern LLMs perform better when given specific expertise personas with relevant context about their capabilities and knowledge domains.

**Impact:** Suboptimal responses due to lack of clear expertise framing.

---

### 3.2 No Few-Shot Examples Despite Infrastructure

**Issue:** The database has infrastructure for few-shot prompting (ACCEPTED/REJECTED operations preserved), but it's not used.

**Evidence:**
- Index exists: `ix_operations_status_prompt_hash`
- Historical operations preserved
- No query retrieving examples in `plan` command

**Impact:** Missing opportunity to improve suggestion quality by showing successful examples.

---

### 3.3 Content Truncation Strategy is Suboptimal

**Issue:** Current truncation keeps only the beginning of documents.

**Current Implementation:**
```python
def _truncate_content_smart(content, max_chars=4000):
    # Only keeps beginning
    truncated = content[:available_chars].rstrip()
    return f"{truncated}{marker}", True
```

**Problems:**
1. **Loses important end content:** Many documents have key information at the end (signatures, totals, dates, contact info)
2. **No semantic awareness:** Truncates mid-sentence or mid-section
3. **Fixed limit:** 4000 characters may be too restrictive for complex documents or too generous for simple ones

**Research Finding:** Studies show keeping both beginning and end (with middle truncation) preserves more useful context for classification tasks.

---

### 3.4 Guidelines Are Numbered but Not Prioritized

**Issue:** Guidelines are presented as equal-weight numbered list.

**Current:**
```
Guidelines:
1. suggested_directory_path should be...
2. suggested_filename should include...
3. reason should be...
4. Base your suggestions on...
5. Follow the document organization instructions
6. When existing values are shown...
```

**Problems:**
1. Most important guideline (#5 - follow instructions) is buried at position 5
2. Guideline #6 (use existing values) is critical but last
3. No emphasis on priority hierarchy

---

### 3.5 Filename Convention Instructions Are Unclear

**Issue:** The relationship between default and folder-specific conventions is ambiguous.

**Current:**
```markdown
**Default Convention**: `{year}-{month}-{description}`
  - This convention applies to all folders unless overridden below

**Folder-Specific Conventions**:
  - `Financial/invoices`: `{company}-invoice-{year}-{month}`
```

**Problems:**
1. No explicit instruction to "replace" vs "ignore" default for specific folders
2. Inheritance rules not explained (do nested folders inherit from parent folder convention or default?)
3. No guidance on handling partial matches

---

### 3.6 Variable Pattern Extraction Lacks Examples

**Issue:** Pattern descriptions are provided but without concrete examples.

**Current:**
```markdown
**year**:
  - 4-digit year in YYYY format

**company**:
  - Company name extracted from invoice header
```

**Better:**
```markdown
**year**:
  - 4-digit year in YYYY format
  - Examples: "2024" (from "Date: January 15, 2024"), "2023" (from "FY2023 Report")
```

**Impact:** LLMs perform better with concrete examples, especially for extraction tasks.

---

### 3.7 No Handling of Ambiguous Documents

**Issue:** No guidance for edge cases or ambiguous situations.

**Missing guidance for:**
- Documents that could fit multiple folders
- Documents with missing information (no date, unknown company)
- Documents in unexpected languages
- Corrupted or unreadable content
- Multi-topic documents

---

### 3.8 Gemini Provider Combines System and User Prompts

**Issue:** Google Gemini implementation concatenates prompts instead of using separate roles.

**Current:**
```python
combined_prompt = f"{system_prompt}\n\n{user_prompt}"
response = self.model.generate_content(combined_prompt)
```

**Better:** Use Gemini's `system_instruction` parameter for proper role separation:
```python
model = genai.GenerativeModel(
    model_name,
    system_instruction=system_prompt
)
response = model.generate_content(user_prompt)
```

**Impact:** Proper role separation improves instruction following and reduces prompt injection risks.

---

### 3.9 No Temperature Control Based on Task

**Issue:** Fixed temperature (0.7) regardless of certainty needs.

**Current (OpenAI):**
```python
"temperature": 0.7
```

**Gemini:** Uses default (no explicit setting)

**Problem:** Document organization is largely deterministic - the same document should always go to the same place. Lower temperature (0.2-0.3) would improve consistency.

---

### 3.10 Missing Output Format Validation Instructions

**Issue:** For non-structured-output providers, format instructions could be more explicit.

**Current:**
```
Return ONLY the JSON object, no additional text or markdown formatting.
```

**Problems:**
1. Doesn't specify encoding (UTF-8)
2. Doesn't mention escaping special characters
3. Doesn't specify null/empty handling
4. Some models still wrap in markdown despite instruction

---

### 3.11 Reason Field Lacks Purpose Definition

**Issue:** The `reason` field purpose is unclear to the LLM.

**Current:**
```
reason should be a brief explanation (1-2 sentences) of why this makes sense
```

**Problems:**
1. Doesn't specify WHO the reason is for (user? debugging? audit trail?)
2. Doesn't specify what to include (confidence level? alternatives considered?)
3. "why this makes sense" is vague

---

### 3.12 No Confidence or Alternative Suggestions

**Issue:** Current schema only captures single suggestion with no confidence indicator.

**Current Schema:**
```python
class OrganizationSuggestion(BaseModel):
    suggested_directory_path: str
    suggested_filename: str
    reason: str
```

**Missing:**
- Confidence score (0-1)
- Alternative suggestions
- Warning flags for edge cases

---

### 3.13 Instruction Generation Order is Suboptimal

**Issue:** The most important information comes after less critical details.

**Current order in generated instructions:**
1. Folder hierarchy (structure)
2. Filename conventions (secondary)
3. Variable patterns (guidance)

**Better order:**
1. Task overview (what to do)
2. Variable patterns (how to extract)
3. Folder hierarchy (where to place)
4. Filename conventions (how to name)

This follows a logical decision flow.

---

### 3.14 No Chain-of-Thought Prompting Option

**Issue:** For complex decisions, no option to request reasoning before answer.

**Research Finding:** Chain-of-thought prompting improves accuracy for multi-step reasoning tasks.

---

### 3.15 Markdown in XML Creates Parsing Ambiguity

**Issue:** Instructions use markdown formatting inside XML tags.

**Current:**
```xml
<organizationInstructions>
# Document Organization Structure

- **Financial/** - Financial documents
</organizationInstructions>
```

**Problem:** Mixing formats can confuse models about how to interpret the content.

---

## 4. Specific Recommendations

### 4.1 Enhanced System Prompt

**Priority: HIGH**

Replace the current generic prompt with an expertise-framed version:

```jinja2
You are an expert document management specialist with deep experience in information architecture, records management, and enterprise content organization. Your expertise includes:

- Analyzing document metadata, content, and context clues
- Applying consistent naming conventions and folder structures
- Identifying document types (invoices, contracts, reports, correspondence)
- Extracting key metadata (dates, parties, reference numbers)

Your task is to analyze each document and suggest optimal organization within a defined folder structure.

You will receive:
1. Organization instructions defining the target folder structure and naming conventions (in <organizationInstructions> XML tags)
2. Document content to analyze (in <documentContent> XML tags with the current file path as an attribute)

Based on your analysis, provide a single organization suggestion with:
- The target directory path
- A new filename following conventions
- A brief rationale for your decision
{% if not use_structured_output %}

Respond with this exact JSON structure:
{
    "suggested_directory_path": "relative/path/to/folder",
    "suggested_filename": "new-filename.ext",
    "reason": "Brief explanation of classification rationale"
}
{% endif %}

## Critical Guidelines (in priority order)

1. **Follow organization instructions exactly** - The folder structure and naming conventions in <organizationInstructions> are authoritative
2. **Match existing values when applicable** - If "Existing:" values are shown for a variable folder, use an exact match when the document fits; only create new values for genuinely new categories
3. **Preserve file extensions** - Always keep the original file extension (.pdf, .docx, etc.)
4. **Use forward slashes** - Directory paths use forward slashes regardless of OS (e.g., "finance/invoices/2024")
5. **Extract accurate metadata** - Base suggestions on actual document content, not assumptions
6. **Handle ambiguity explicitly** - If a document could fit multiple folders, choose the most specific match and note alternatives in your reason

## Output Guidelines

- **Path format**: Relative path with forward slashes, no leading or trailing slashes
- **Filename format**: Follow the convention pattern, preserving original extension
- **Reason format**: 1-2 sentences explaining: (a) document type identified, (b) key metadata extracted, (c) why this location is appropriate
{% if not use_structured_output %}

Return ONLY the JSON object. Do not include markdown formatting, code blocks, or any additional text.
{% endif %}
```

---

### 4.2 Implement Few-Shot Learning

**Priority: HIGH**

Add few-shot examples from historical ACCEPTED operations:

```python
def get_few_shot_examples(
    session: Session,
    prompt_hash: str,
    limit: int = 3
) -> list[dict]:
    """Retrieve successful examples for few-shot prompting."""
    from docman.models import Operation, DocumentCopy, Document

    examples = (
        session.query(Operation)
        .join(DocumentCopy)
        .join(Document)
        .filter(Operation.status == OperationStatus.ACCEPTED)
        .filter(Operation.prompt_hash == prompt_hash)
        .order_by(Operation.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "file_path": op.document_copy.file_path,
            "content_preview": op.document_copy.document.content[:500],
            "directory": op.suggested_directory_path,
            "filename": op.suggested_filename,
            "reason": op.reason
        }
        for op in examples
    ]
```

Then include in the user prompt:

```jinja2
{% if few_shot_examples %}
## Previous Successful Classifications

{% for ex in few_shot_examples %}
**Example {{ loop.index }}:**
- Original: `{{ ex.file_path }}`
- Content preview: {{ ex.content_preview[:200] }}...
- Classified as: `{{ ex.directory }}/{{ ex.filename }}`
- Rationale: {{ ex.reason }}

{% endfor %}
---
{% endif %}
```

---

### 4.3 Improve Content Truncation

**Priority: MEDIUM**

Implement head-and-tail preservation:

```python
def _truncate_content_smart(
    content: str,
    max_chars: int = 4000,
    head_ratio: float = 0.6,
    tail_ratio: float = 0.3,
) -> tuple[str, bool]:
    """Truncate content preserving beginning and end.

    Keeps head_ratio of content from beginning and tail_ratio from end,
    with middle section removed. This preserves document headers and
    footers which often contain critical metadata.
    """
    if len(content) <= max_chars:
        return content, False

    # Calculate marker first
    estimated_removed = len(content) - max_chars
    marker = f"\n\n[... {estimated_removed:,} characters omitted ...]\n\n"

    available = max_chars - len(marker)
    if available < 100:
        # Edge case: very small limit
        return content[:max_chars], True

    head_chars = int(available * head_ratio)
    tail_chars = int(available * tail_ratio)

    head = content[:head_chars].rstrip()
    tail = content[-tail_chars:].lstrip() if tail_chars > 0 else ""

    return f"{head}{marker}{tail}", True
```

---

### 4.4 Add Concrete Examples to Variable Patterns

**Priority: MEDIUM**

Enhance `_get_pattern_guidance` to include examples:

```python
def _get_pattern_guidance(variable_name: str, repo_root: Path) -> str:
    patterns = get_variable_patterns(repo_root)

    if variable_name not in patterns:
        # ... existing warning code ...
        return f"\n  - Infer {variable_name} from document context"

    description = patterns[variable_name]

    # Add common examples based on pattern name
    examples = _get_common_examples(variable_name)
    example_str = f" (e.g., {examples})" if examples else ""

    return f"\n  - {description}{example_str}"

def _get_common_examples(pattern_name: str) -> str:
    """Get common examples for standard patterns."""
    examples = {
        "year": '"2024", "2023"',
        "month": '"01", "12"',
        "date": '"2024-01-15"',
        "company": '"Acme Corp", "XYZ Inc"',
        "category": '"utilities", "office-supplies"',
    }
    return examples.get(pattern_name.lower(), "")
```

---

### 4.5 Use Proper Role Separation for Gemini

**Priority: MEDIUM**

Update `GoogleGeminiProvider` to use system instruction:

```python
def __init__(self, config: ProviderConfig, api_key: str):
    super().__init__(config, api_key)
    import google.generativeai as genai

    genai.configure(api_key=api_key)

    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=OrganizationSuggestion,
    )

    self._genai = genai
    self._model_name = config.model
    self._generation_config = generation_config
    self._system_prompt = None  # Set when calling generate_suggestions

def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    # Create model with system instruction
    model = self._genai.GenerativeModel(
        self._model_name,
        generation_config=self._generation_config,
        system_instruction=system_prompt,
    )

    response = model.generate_content(user_prompt)
    # ... rest of processing
```

---

### 4.6 Lower Temperature for Consistency

**Priority: MEDIUM**

Add configurable temperature with lower default:

```python
# In llm_config.py or provider
DEFAULT_TEMPERATURE = 0.2  # Lower for deterministic task

# In OpenAICompatibleProvider
request_params = {
    "model": self.config.model,
    "messages": [...],
    "temperature": getattr(self.config, 'temperature', DEFAULT_TEMPERATURE),
}

# In GoogleGeminiProvider
generation_config = genai.GenerationConfig(
    response_mime_type="application/json",
    response_schema=OrganizationSuggestion,
    temperature=getattr(config, 'temperature', DEFAULT_TEMPERATURE),
)
```

---

### 4.7 Add Ambiguity Handling Instructions

**Priority: MEDIUM**

Add section to organization instructions:

```python
# In generate_instructions_from_folders()
sections.append("\n# Handling Edge Cases\n")
sections.append("""
When documents are ambiguous or don't clearly fit a single folder:

1. **Multiple possible folders**: Choose the most specific match. Mention alternatives in the reason.
2. **Missing date**: Use "0000" or the current year if the document type typically needs a date.
3. **Unknown company/entity**: Use "unknown" or extract the most prominent name from the content.
4. **Unreadable content**: Use file name patterns and extension to make best guess.
5. **Multi-topic documents**: Classify by primary topic or most prominent subject.
""")
```

---

### 4.8 Enhanced Schema with Confidence

**Priority: LOW**

Extend the Pydantic model (requires migration):

```python
class OrganizationSuggestion(BaseModel):
    suggested_directory_path: str
    suggested_filename: str
    reason: str
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0"
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="Alternative folder paths considered"
    )

    # ... existing validators
```

Update prompt to request these fields when structured output is not supported.

---

### 4.9 Clarify Reason Field Purpose

**Priority: LOW**

Update guideline in system prompt:

```
- **Reason format**: 1-2 sentences for audit trail, including:
  (a) Document type identified (e.g., "Invoice", "Contract", "Report")
  (b) Key metadata extracted (e.g., "Date: 2024-01, Company: Acme")
  (c) Why this folder matches (e.g., "Matches existing '2024' year folder")
```

---

### 4.10 Add Chain-of-Thought Option

**Priority: LOW**

For complex folder structures, enable reasoning mode:

```jinja2
{% if use_chain_of_thought %}
Before providing your suggestion, briefly analyze:
1. Document type and key metadata found
2. Which folders could potentially match
3. Why the chosen folder is the best fit

Then provide your JSON suggestion.
{% endif %}
```

This can be enabled for repositories with deep folder hierarchies (>3 levels).

---

## 5. Priority Matrix

| Recommendation | Priority | Effort | Impact | Dependencies |
|----------------|----------|--------|--------|--------------|
| 4.1 Enhanced System Prompt | HIGH | Low | High | None |
| 4.2 Few-Shot Learning | HIGH | Medium | High | Database |
| 4.3 Improved Truncation | MEDIUM | Low | Medium | None |
| 4.4 Variable Pattern Examples | MEDIUM | Low | Medium | None |
| 4.5 Gemini Role Separation | MEDIUM | Low | Medium | Provider code |
| 4.6 Lower Temperature | MEDIUM | Low | Medium | Config |
| 4.7 Ambiguity Handling | MEDIUM | Low | Medium | Prompt template |
| 4.8 Enhanced Schema | LOW | High | Medium | DB migration |
| 4.9 Clarify Reason Purpose | LOW | Low | Low | Prompt template |
| 4.10 Chain-of-Thought | LOW | Medium | Low | Prompt template |

### Suggested Implementation Order

**Phase 1 (Quick Wins):**
1. Enhanced System Prompt (4.1)
2. Lower Temperature (4.6)
3. Clarify Reason Purpose (4.9)

**Phase 2 (Medium Effort):**
4. Variable Pattern Examples (4.4)
5. Improved Truncation (4.3)
6. Gemini Role Separation (4.5)
7. Ambiguity Handling (4.7)

**Phase 3 (Higher Effort):**
8. Few-Shot Learning (4.2)
9. Chain-of-Thought Option (4.10)
10. Enhanced Schema (4.8)

---

## 6. Implementation Notes

### Testing Considerations

1. **A/B Testing**: Compare suggestion quality before/after each change
2. **Regression Testing**: Ensure existing test cases still pass
3. **Cost Monitoring**: Track token usage changes (enhanced prompts use more tokens)
4. **Consistency Metrics**: Measure if same document gets same suggestion across runs

### Backward Compatibility

- Changes to `OrganizationSuggestion` schema require database migration
- New prompt hash computation will invalidate all existing operations (requires regeneration)
- Few-shot examples require operations with `prompt_hash` to exist

### Cost Implications

| Change | Token Impact |
|--------|--------------|
| Enhanced System Prompt | +150 tokens/request |
| Few-Shot Examples (3) | +300 tokens/request |
| Ambiguity Handling | +100 tokens/request |
| Chain-of-Thought | +50 output tokens |

Estimated increase: 10-20% per request, but potentially fewer retry calls due to better accuracy.

### Monitoring Recommendations

After implementing changes, monitor:
- **Acceptance rate**: % of suggestions accepted by users
- **Edit distance**: How much users modify suggested paths/names
- **Retry rate**: How often users run `plan` on same document multiple times
- **Error rate**: Provider errors, validation failures, empty responses

---

## Conclusion

The docman prompt engineering system has a solid foundation with good architectural decisions. The most impactful improvements are:

1. **Enhanced system prompt** - Better role framing and priority-ordered guidelines
2. **Few-shot learning** - Leverage existing infrastructure for concrete examples
3. **Improved truncation** - Preserve both head and tail of documents
4. **Lower temperature** - Improve consistency for deterministic task
5. **Gemini role separation** - Use native system instruction support

These changes should improve suggestion quality, reduce user corrections, and provide more consistent results across runs.

---

*Report generated: 2025-11-20*
*Analysis scope: /home/user/docman prompt engineering system*
