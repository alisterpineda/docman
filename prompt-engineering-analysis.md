# Deep Analysis of Prompt Engineering System

## Current Architecture Overview

The system uses a two-template approach:
- **System prompt** (`system_prompt.j2`): Defines role and output format
- **User prompt** (`user_prompt.j2`): Contains organization instructions and document content

Prompts are conditionally adapted for structured output (when providers support it) vs manual JSON parsing.

---

## Critical Issues and Improvements

### 1. **Content Truncation Strategy is Suboptimal**

**Current Implementation** (line 21-54 in `prompt_builder.py`):
```python
truncated = content[:available_chars].rstrip()
```

**Problem**: Only keeps the beginning of documents. Critical metadata often appears at the end:
- Invoices: totals, payment terms, signatures
- Contracts: signature dates, effective dates
- Reports: conclusions, recommendations

**Recommended Fix**:
```python
def _truncate_content_smart(content: str, max_chars: int = 4000) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False

    # Reserve space for marker
    marker = "\n\n[... content truncated ...]\n\n"
    available = max_chars - len(marker)

    # Split: 60% beginning, 40% end
    beginning_chars = int(available * 0.6)
    end_chars = available - beginning_chars

    beginning = content[:beginning_chars].rstrip()
    end = content[-end_chars:].lstrip()

    return f"{beginning}{marker}{end}", True
```

**Impact**: Better extraction of dates, totals, signatures from document ends.

---

### 2. **System Prompt Lacks Clarity and Specificity**

**Current** (`system_prompt.j2` lines 1-6):
```
You are a document organization assistant. Your task is to analyze documents...
```

**Problems**:
- Generic role definition
- No expertise framing
- No success criteria
- No mention of confidence calibration

**Recommended Rewrite**:
```jinja2
You are an expert document management specialist with deep knowledge of filing systems, metadata extraction, and information architecture. Your task is to analyze documents and determine optimal organization within a defined folder structure.

Your goal is to:
1. Extract key metadata (dates, names, document type, topics) from the content
2. Match the document to the most appropriate folder based on its purpose and content
3. Generate a descriptive filename following naming conventions
4. Provide a confidence level that accurately reflects certainty

Success criteria:
- Correct folder placement based on document type and content
- Filename captures essential identifying information
- Variables are extracted accurately from document content
- Confidence reflects actual certainty (high for clear matches, low for ambiguous cases)

{% if not use_structured_output %}
[JSON format instructions...]
{% endif %}
```

---

### 3. **Missing Truncation Awareness in Prompts**

**Current**: The `was_truncated` variable exists but isn't used in templates.

**Problem**: LLM doesn't know content was truncated, may make incorrect inferences.

**Add to user_prompt.j2**:
```jinja2
<documentContent filePath="{{ file_path }}"{% if was_truncated %} truncated="true"{% endif %}>
{{ content }}
</documentContent>
{% if was_truncated %}
<note>Document content was truncated due to length. Key information may appear in both shown portions.</note>
{% endif %}
```

---

### 4. **No Few-Shot Learning Despite Infrastructure**

**Current State**:
- Database has `ix_operations_status_prompt_hash` index for few-shot queries
- Historical ACCEPTED/REJECTED operations are preserved
- **But prompts never use them**

**High-Impact Improvement**: Add few-shot examples to system prompt:

```python
def build_system_prompt_with_examples(
    use_structured_output: bool,
    session: Session,
    prompt_hash: str,
    max_examples: int = 3
) -> str:
    """Build system prompt with few-shot examples from accepted operations."""

    # Query historical accepted operations with same prompt hash
    examples = session.query(Operation).filter(
        Operation.status == OperationStatus.ACCEPTED,
        Operation.prompt_hash == prompt_hash
    ).order_by(Operation.updated_at.desc()).limit(max_examples).all()

    template = _template_env.get_template("system_prompt.j2")
    return template.render(
        use_structured_output=use_structured_output,
        examples=examples
    )
```

**Updated template section**:
```jinja2
{% if examples %}
## Examples of Correct Organization

Here are examples of documents that were correctly organized:
{% for ex in examples %}

**Example {{ loop.index }}:**
- Original path: `{{ ex.document_copy.file_path }}`
- Organized to: `{{ ex.suggested_directory_path }}/{{ ex.suggested_filename }}`
- Reason: {{ ex.reason }}
{% endfor %}
{% endif %}
```

**Impact**: Dramatically improves consistency by learning from user preferences.

---

### 5. **Provider Prompt Handling Differs Suboptimally**

**Current** (Gemini in `llm_providers.py` line 241):
```python
combined_prompt = f"{system_prompt}\n\n{user_prompt}"
```

**Problem**: Gemini receives system + user as single string, losing role separation benefits.

**Recommended**: Use Gemini's system instruction feature:
```python
self.model = genai.GenerativeModel(
    config.model,
    system_instruction=system_prompt,  # Separate system instruction
    generation_config=generation_config,
)

def generate_suggestions(self, system_prompt: str, user_prompt: str):
    # System prompt already set in model initialization
    response = self.model.generate_content(user_prompt)
```

---

### 6. **Temperature Too High for Deterministic Task**

**Current** (OpenAI provider line 463):
```python
"temperature": 0.7,
```

**Problem**: Document organization should be consistent and deterministic.

**Recommendation**: Use `temperature: 0.2` or `0.3` for more consistent results across runs.

---

### 7. **Guidelines Lack Specificity and Prioritization**

**Current Guidelines** (system_prompt.j2 lines 18-24):
```
Guidelines:
1. suggested_directory_path should be a relative path...
2. suggested_filename should include the file extension...
3. reason should be a brief explanation...
4. Base your suggestions on... and any other relevant metadata
5. Follow the document organization instructions
```

**Problems**:
- No priority order
- "Any other relevant metadata" is vague
- No guidance for edge cases

**Recommended Rewrite**:
```jinja2
## Guidelines (in priority order)

1. **Follow organization instructions strictly**: The folder structure and naming conventions provided must be followed exactly.

2. **Extract variables accurately**: When filename conventions include variables like {year} or {company}, extract these values precisely from the document content. If a value cannot be determined with confidence, use "unknown" as placeholder.

3. **Path format**: Use relative paths with forward slashes (e.g., "finance/invoices/2024"). Never use absolute paths or backslashes.

4. **Preserve file extension**: The suggested_filename must end with the same extension as the original file (.pdf, .docx, etc.).

5. **Prioritize extraction sources**:
   - Dates: Look for explicit dates, "Date:", timestamps, or dated signatures
   - Names/Companies: Headers, letterheads, "From:", "To:", signatures
   - Document type: Subject lines, titles, form numbers

6. **Handle ambiguity**: If a document could fit multiple folders, choose the most specific match. If uncertain, reflect this in a lower confidence score.

7. **Reason format**: Explain what metadata you extracted and why the suggested location is appropriate (1-2 sentences).
```

---

### 8. **Variable Pattern Guidance Lacks Examples**

**Current** (`_get_pattern_guidance` in prompt_builder.py):
```python
return f"\n  - {description}"
```

**Example output**:
```
**year**:
  - 4-digit year in YYYY format
```

**Problem**: No concrete extraction examples.

**Improved Implementation**:
```python
def _get_pattern_guidance(variable_name: str, repo_root: Path) -> str:
    patterns = get_variable_patterns(repo_root)

    if variable_name not in patterns:
        # ... warning code ...
        return f"\n  - Infer {variable_name} from document context"

    description = patterns[variable_name]

    # Add extraction hints based on common patterns
    hints = {
        "year": "Look for dates like '2024', 'January 2024', '01/15/2024'",
        "month": "Extract from dates, use 2-digit format (01-12)",
        "company": "Check letterhead, 'From:', or signature block",
        "category": "Determine from document purpose/content type",
    }

    extraction_hint = hints.get(variable_name.lower(), "Extract from document content")

    return f"\n  - {description}\n    Extraction hint: {extraction_hint}"
```

---

### 9. **No Explicit Handling of Edge Cases**

Add to system prompt:
```jinja2
## Edge Case Handling

- **Unreadable/corrupt content**: If document content is mostly garbled or unreadable, set confidence to 0.0 and explain in reason.

- **No matching folder**: If document doesn't fit any defined folder, choose the closest match and explain the mismatch in reason with low confidence.

- **Multiple possible folders**: Choose the most specific folder. Example: An invoice about office supplies goes in "Financial/invoices/{year}" not "Office/{category}".

- **Missing variables**: If a required variable (like year) cannot be extracted, use "unknown" and note this in the reason.

- **Non-standard filenames**: Normalize to lowercase, replace spaces with hyphens, remove special characters.
```

---

### 10. **Confidence Score Lacks Calibration Guidance**

**Current**: No guidance on what confidence values mean.

**Add to guidelines**:
```jinja2
8. **Confidence calibration**:
   - 0.9-1.0: Document clearly matches folder, all variables extracted with certainty
   - 0.7-0.89: Good match, most variables clear, minor uncertainty
   - 0.5-0.69: Reasonable match, some variables inferred or uncertain
   - 0.3-0.49: Weak match, significant uncertainty in folder or variables
   - 0.0-0.29: Poor match, document may not belong in defined structure
```

---

### 11. **Output Verification Step Missing**

Add self-verification instruction:
```jinja2
## Before Finalizing

Verify your suggestion:
- [ ] Directory path uses defined folder structure
- [ ] Filename follows the convention for that folder (or default)
- [ ] All variables in filename are extracted from content
- [ ] File extension is preserved
- [ ] Confidence accurately reflects certainty
```

---

### 12. **Prompt Structure Could Be Reordered**

**Current order** in user prompt:
1. Organization instructions
2. Document content

**Recommendation**: For long documents, consider:
1. **Brief task reminder** (what to extract)
2. **Document content** (the input)
3. **Organization instructions** (rules to apply)

This follows the "input before instructions" pattern that can improve comprehension for some models. However, test both orderings empirically.

---

### 13. **No Negative Examples or Anti-Patterns**

Add to system prompt:
```jinja2
## Common Mistakes to Avoid

- DON'T use absolute paths like "/home/user/documents/..."
- DON'T include path traversal like "../"
- DON'T lose the file extension
- DON'T guess dates that aren't in the document (use current year only if document clearly references it)
- DON'T create new folders outside the defined structure
- DON'T use spaces in filenames (use hyphens instead)
```

---

## Implementation Priority

### High Priority (Significant Impact)
1. **Few-shot learning from accepted operations** - Leverages existing infrastructure, high impact on consistency
2. **Smart content truncation** (beginning + end) - Captures critical metadata
3. **System prompt clarity and specificity** - Better task understanding
4. **Confidence calibration guidance** - More useful confidence scores

### Medium Priority
5. **Truncation awareness in prompts** - Prevents incorrect inferences
6. **Variable pattern extraction hints** - Better variable extraction
7. **Edge case handling** - Reduces failures on unusual documents
8. **Temperature reduction** - More consistent results

### Lower Priority (Polish)
9. **Self-verification checklist** - Catches errors
10. **Negative examples** - Prevents common mistakes
11. **Gemini system instruction separation** - Cleaner architecture
12. **Output verification step** - Additional quality check

---

## Summary

The current prompt engineering is functional but basic. The highest-impact improvements are:

1. **Use the few-shot infrastructure that already exists** - The database is designed for this but it's not implemented
2. **Improve content truncation** to capture document endings
3. **Add specificity and calibration** to system prompt guidelines
4. **Lower temperature** for deterministic consistency

These changes would significantly improve organization accuracy, variable extraction, and confidence calibration without requiring architectural changes to the codebase.
