# Prompt Engineering Analysis: Low Priority Improvements

**Analysis Date:** 2025-11-20
**Scope:** docman LLM prompt system future enhancements and refinements

---

## Executive Summary

This document identifies low-priority improvements that represent future enhancements, nice-to-have features, and polish items. These can be implemented after the high and medium priority items are addressed.

---

## 1. Internationalization and Localization

### 1.1 All Prompts in English Only

**Issue:** All prompt text is hardcoded in English:
- System prompt role and instructions
- Guidelines and tips
- Generated organization instructions

**Impact:**
- Non-English speakers get English prompts
- LLM may respond in English even if user prefers another language
- Document content in other languages may be misinterpreted

**Recommendation:** Implement i18n for prompts:

```python
# prompts/en/system_prompt.j2
# prompts/es/system_prompt.j2
# prompts/de/system_prompt.j2

def build_system_prompt(use_structured_output: bool = False, locale: str = "en") -> str:
    template = _template_env.get_template(f"{locale}/system_prompt.j2")
    ...
```

**Note:** This is low priority because:
- Translating technical prompts requires expertise
- Most LLMs perform best with English prompts
- Can be worked around with user-defined variable pattern descriptions in native language

---

### 1.2 Date Format Assumptions

**Issue:** Pattern guidance assumes US date formats:
- "YYYY-MM-DD format"
- Month first in examples

**Opportunity:** Add locale-aware date format hints:

```python
LOCALE_DATE_FORMATS = {
    "en-US": "MM/DD/YYYY or YYYY-MM-DD",
    "en-GB": "DD/MM/YYYY or YYYY-MM-DD",
    "de-DE": "DD.MM.YYYY",
    "ja-JP": "YYYY年MM月DD日",
}
```

---

## 2. Advanced Content Analysis

### 2.1 No Semantic Chunking

**Issue:** Content truncation uses character count only:

```python
head_chars = available // 2
tail_chars = available - head_chars
```

**Opportunity:** Use semantic chunking to preserve meaningful sections:
- Keep complete paragraphs
- Preserve tables entirely or not at all
- Identify and retain headers/summaries
- Keep bullet point lists together

**Implementation Complexity:** Requires NLP processing (sentence boundary detection, section identification).

**Recommendation (long-term):**

```python
def _truncate_content_semantic(content: str, max_chars: int = 8000) -> str:
    # Parse document structure
    sections = identify_sections(content)

    # Score sections by importance
    scored_sections = [
        (section, score_importance(section))
        for section in sections
    ]

    # Select highest-scoring sections within limit
    selected = select_within_budget(scored_sections, max_chars)

    return combine_sections(selected)
```

---

### 2.2 No Image/Table Handling in PDFs

**Issue:** docling extracts text from PDFs, but images and tables lose context.

**Opportunity:** For PDFs with images:
- Extract image captions
- Note image presence in prompt
- Use multimodal LLMs (GPT-4 Vision, Gemini Vision)

**Long-term vision:**

```python
class MultimodalPromptBuilder:
    def build_user_prompt(self, file_path: str, content: str, images: list[bytes]) -> dict:
        return {
            "text": self.build_text_prompt(content),
            "images": [
                {"data": img, "caption": f"Image {i+1} from document"}
                for i, img in enumerate(images)
            ]
        }
```

---

### 2.3 No OCR Quality Indicators

**Issue:** For scanned documents, OCR quality varies significantly.

**Opportunity:** Indicate OCR confidence to LLM:

```
<documentContent filePath="scan.pdf" ocrConfidence="0.85">
...
</documentContent>
```

This helps the LLM:
- Treat low-confidence text with more flexibility
- Suggest "REVIEW_NEEDED" for very low confidence
- Account for potential OCR errors

---

## 3. Advanced LLM Features

### 3.1 No Streaming Support

**Issue:** LLM responses are returned all at once after completion.

**Opportunity:** Streaming provides better UX for long operations:
- Real-time feedback during generation
- Early termination if off-track
- Progress indication

**Implementation:**

```python
class OpenAICompatibleProvider(LLMProvider):
    def generate_suggestions_streaming(self, system_prompt: str, user_prompt: str):
        for chunk in self.client.chat.completions.create(
            ...,
            stream=True
        ):
            yield chunk.choices[0].delta.content
```

**Use case:** The `review --apply-all` command with many files could show real-time progress.

---

### 3.2 No Confidence Scoring

**Issue:** LLM provides binary suggestions without confidence level.

**Opportunity:** Request confidence scores:

```python
class OrganizationSuggestion(BaseModel):
    suggested_directory_path: str
    suggested_filename: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    alternatives: list[dict] | None = None
```

**Benefits:**
- Flag low-confidence suggestions for manual review
- Provide alternative suggestions for ambiguous documents
- Track confidence trends for prompt optimization

---

### 3.3 No Function Calling

**Issue:** The system uses JSON output but not function calling.

**Opportunity:** Function calling provides:
- Stricter schema enforcement
- Better tool integration
- Clearer intent signaling

**Example:**

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "suggest_organization",
            "description": "Suggest file organization for a document",
            "parameters": OrganizationSuggestion.model_json_schema()
        }
    }
]

response = self.client.chat.completions.create(
    ...,
    tools=tools,
    tool_choice={"type": "function", "function": {"name": "suggest_organization"}}
)
```

---

## 4. User Experience Enhancements

### 4.1 No Prompt Preview Before Sending

**Issue:** Users can only see prompts via `debug-prompt` after configuration.

**Opportunity:** Add interactive prompt preview:

```bash
$ docman plan --preview
Preview of prompts for 5 documents:

[1] inbox/invoice.pdf
    Estimated tokens: 2,450
    Content truncated: Yes (8,000 of 45,000 chars)

[2] inbox/report.pdf
    Estimated tokens: 1,200
    Content truncated: No

Total estimated tokens: 12,500
Estimated cost: $0.025 (GPT-4)

Proceed? [y/N]
```

---

### 4.2 No Prompt History or Versioning

**Issue:** Changes to prompts aren't tracked or versioned.

**Opportunity:** Track prompt changes over time:
- Compare prompt versions
- Roll back to previous prompts
- Analyze which prompts produce better results

**Implementation:** Store prompt versions in database:

```python
class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True)
    prompt_hash = Column(String, index=True)
    system_prompt = Column(Text)
    organization_instructions = Column(Text)
    model_name = Column(String)
    created_at = Column(DateTime)
    acceptance_rate = Column(Float)  # Track effectiveness
```

---

### 4.3 No A/B Testing Support

**Issue:** No way to compare different prompt versions.

**Opportunity:** A/B test prompt variations:
- Compare different guideline orderings
- Test few-shot vs zero-shot
- Evaluate different instruction formats

**Long-term vision:**

```bash
$ docman plan --experiment "verbose-guidelines"
$ docman plan --experiment "concise-guidelines"
$ docman experiment compare
```

---

## 5. Documentation and Debugging

### 5.1 No Prompt Documentation

**Issue:** The prompt design rationale isn't documented.

**Recommendation:** Add documentation for:
- Why XML tags are used
- Why guidelines are ordered as they are
- Why 8000 character limit was chosen
- Expected LLM behavior

**Location:** `docs/prompt-engineering.md`

---

### 5.2 Debug Output Could Be Richer

**Issue:** `debug-prompt` shows raw prompts only.

**Opportunity:** Add analysis to debug output:
- Estimated token count
- Variable patterns detected
- Existing directories found
- Truncation details
- Hash computation breakdown

---

### 5.3 No Prompt Linting

**Opportunity:** Lint prompts for common issues:
- Undefined variable patterns
- Conflicting guidelines
- Missing required sections
- Excessive length

```bash
$ docman lint-prompts
Warning: Variable pattern {company} used but not defined
Warning: Prompt exceeds 10,000 tokens (estimated 12,500)
Error: No filename convention defined for folder "invoices"
```

---

## 6. Integration Enhancements

### 6.1 No Webhook/Callback Support

**Opportunity:** Integrate with external systems:
- Notify when suggestions ready
- Post results to external API
- Trigger workflows on organization

---

### 6.2 No Plugin System for Custom Prompts

**Opportunity:** Allow users to customize prompts without modifying code:
- User-defined system prompt additions
- Custom guideline sections
- Organization-specific rules

```yaml
# .docman/config.yaml
prompts:
  custom_guidelines:
    - "Always use lowercase for filenames"
    - "Prepend project code to all documents"
  custom_system_prompt_append: |
    Additional context: This is a legal firm specializing in IP law.
```

---

## 7. Performance Benchmarking

### 7.1 No Performance Metrics

**Opportunity:** Track and optimize:
- Prompt generation time
- LLM response time
- Token usage per document
- Cache hit rates

```python
@dataclass
class PromptMetrics:
    generation_time_ms: float
    token_count: int
    cache_hit: bool
    truncation_ratio: float
```

---

### 7.2 No Batch Optimization

**Issue:** Each document gets its own LLM call.

**Opportunity:** Batch similar documents:
- Send multiple small documents in one call
- Reduce API overhead
- Potentially lower cost

**Note:** This requires careful prompt engineering to handle multiple documents clearly.

---

## 8. Testing Refinements

### 8.1 No Property-Based Testing

**Opportunity:** Use Hypothesis for comprehensive testing:

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=0, max_size=100000))
def test_truncation_never_exceeds_limit(content):
    result, _, _, _ = _truncate_content_smart(content, max_chars=8000)
    assert len(result) <= 8000 + 100  # Allow marker overhead
```

---

### 8.2 No Fuzzing for Security

**Opportunity:** Fuzz test prompt construction with malicious inputs:
- XML injection attempts
- Unicode edge cases
- Path traversal in file names
- Extremely long content

---

### 8.3 No Load Testing

**Opportunity:** Test performance at scale:
- 1000 documents in single plan
- Multiple concurrent plan commands
- Large folder structures (1000+ definitions)

---

## 9. Future Provider Support

### 9.1 No Anthropic Claude Support

**Opportunity:** Add Anthropic provider:

```python
class AnthropicProvider(LLMProvider):
    @property
    def supports_structured_output(self) -> bool:
        return True  # Via tool_use

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict:
        response = self.client.messages.create(
            model=self.config.model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[{
                "name": "suggest_organization",
                "input_schema": OrganizationSuggestion.model_json_schema()
            }]
        )
        ...
```

---

### 9.2 No Local Model Support

**Opportunity:** Support local models via Ollama:

```python
class OllamaProvider(LLMProvider):
    @property
    def supports_structured_output(self) -> bool:
        return False  # Most local models don't support schemas

    def generate_suggestions(self, system_prompt: str, user_prompt: str) -> dict:
        response = requests.post(
            f"{self.config.endpoint}/api/generate",
            json={
                "model": self.config.model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
            }
        )
        ...
```

---

### 9.3 No Model Comparison Tools

**Opportunity:** Compare model performance:

```bash
$ docman compare-models --files inbox/*.pdf
Model              | Accuracy | Avg Tokens | Cost Est
-------------------|----------|------------|----------
gemini-2.0-flash   | 85%      | 2,100      | $0.003
gpt-4o             | 92%      | 2,400      | $0.024
gpt-4o-mini        | 78%      | 2,300      | $0.002
```

---

## Priority Notes

These improvements are low priority because they:
- Require significant implementation effort
- Have marginal benefit compared to high/medium items
- Are "nice to have" rather than essential
- Depend on high/medium items being completed first

**Suggested timeline:**
- Implement after all high-priority security and reliability fixes
- Implement after medium-priority performance optimizations
- Consider based on user feedback and feature requests

---

## Summary

Low-priority improvements focus on:
- **Future-proofing** through internationalization and advanced features
- **User experience** through previews, history, and A/B testing
- **Performance** through benchmarking and batch optimization
- **Extensibility** through plugins and additional providers

These represent the long-term vision for a mature, feature-rich prompt engineering system that can evolve with user needs and LLM capabilities.
