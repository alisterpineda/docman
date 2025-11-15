# Test Suite Improvement Recommendations

This document contains detailed recommendations for future test suite improvements based on the efficiency analysis completed in 2025-11-15.

## Status Summary

### ✅ Completed Improvements

1. **Shared Fixtures Created** - Added reusable fixtures in `conftest.py`:
   - `db_session` - Database session with automatic cleanup
   - `isolated_repo` - Repository setup fixture
   - `create_scanned_document` - Factory for test documents
   - `create_pending_operation` - Factory for test operations
   - `document_converter` - Module-scoped DocumentConverter for performance
   - `setup_repository()` - Shared helper function

2. **Redundant Tests Removed** - Eliminated 34 tests (~264 lines):
   - Removed duplicate app config integration tests
   - Removed duplicate database schema validation tests
   - Deleted `test_cli_helpers.py` (tested third-party library)
   - Consolidated dataclass serialization tests

3. **Pytest Markers Added** - All 436 tests across 21 files now have markers:
   - `@pytest.mark.unit` - 256 unit tests
   - `@pytest.mark.integration` - 180 integration tests
   - `@pytest.mark.slow` - Computationally intensive tests

**Total Savings So Far:** ~342 lines of code removed, test count reduced from 470 → 436 tests

---

## 🔥 High-Priority Recommendations

### 1. Use Shared Fixtures (Est. ~1,000 lines savings)

**Problem:** 73 instances of manual database session management across 6 files still duplicate the session boilerplate instead of using the `db_session` fixture.

**Files Affected:**
- `test_plan_integration.py` - 31 instances
- `test_review_integration.py` - 23 instances
- `test_dedupe_integration.py` - 9 instances
- `test_scan_integration.py` - 5 instances
- `test_status_integration.py` - 4 instances
- `test_debug_prompt_integration.py` - 1 instance

**Current Pattern (16 lines per test):**
```python
ensure_database()
session_gen = get_session()
session = next(session_gen)
try:
    doc = Document(content_hash="hash", content="content")
    session.add(doc)
    session.commit()
finally:
    try:
        next(session_gen)
    except StopIteration:
        pass
```

**Should be:**
```python
def test_example(db_session):
    doc = Document(content_hash="hash", content="content")
    db_session.add(doc)
    db_session.commit()
```

**Impact:** Eliminates ~350 lines of try/finally boilerplate

---

### 2. Replace Duplicate Setup Methods (Est. ~450 lines savings)

**Problem:** 13 test classes have their own `setup_repository()` and `setup_isolated_env()` methods instead of using shared fixtures.

**Files Affected:**
- `test_plan_integration.py` (2 classes)
- `test_review_integration.py` (3 classes)
- `test_status_integration.py` (1 class)
- `test_dedupe_integration.py` (1 class)
- `test_scan_integration.py` (1 class)
- `test_debug_prompt_integration.py` (1 class)
- `test_llm_commands_integration.py` (6 classes)

**Current Pattern (~20 lines per class):**
```python
def setup_repository(self, path: Path) -> None:
    docman_dir = path / ".docman"
    docman_dir.mkdir()
    config_file = docman_dir / "config.yaml"
    config_content = """
organization:
  variable_patterns:
    year: "4-digit year in YYYY format"
  folders:
    Documents:
      description: "Test documents folder"
"""
    config_file.write_text(config_content)

def setup_isolated_env(self, tmp_path, monkeypatch):
    app_config_dir = tmp_path / "app_config"
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    monkeypatch.setenv("DOCMAN_APP_CONFIG_DIR", str(app_config_dir))
    self.setup_repository(repo_dir)
    return repo_dir
```

**Should be:**
```python
# Use the isolated_repo fixture or setup_repository() helper
from conftest import setup_repository

def test_example(isolated_repo):
    # Repository already set up and configured
    pass

# OR use the helper directly
def test_example(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    setup_repository(repo_dir)
```

**Impact:** Eliminates ~200 lines of duplicate setup code

---

### 3. Use Factory Fixtures (Est. ~240 lines savings)

**Problem:** Test classes have their own `create_scanned_document()` and `create_pending_operation()` methods.

**Files Affected:**
- `test_plan_integration.py` - 2 instances of `create_scanned_document()` (~80 lines)
- `test_review_integration.py` - 2 instances of `create_pending_operation()` (~80 lines)
- `test_status_integration.py` - 1 instance of `create_pending_operation()` (~40 lines)
- `test_debug_prompt_integration.py` - 1 instance of `create_document_in_db()` (~40 lines)

**Current Pattern (~40 lines per method):**
```python
def create_scanned_document(self, repo_dir, file_path, content="Test"):
    ensure_database()
    session_gen = get_session()
    session = next(session_gen)
    try:
        full_path = repo_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        content_hash = compute_content_hash(full_path)
        document = Document(content_hash=content_hash, content=content)
        session.add(document)
        session.flush()
        stat = full_path.stat()
        copy = DocumentCopy(
            document_id=document.id,
            repository_path=str(repo_dir),
            file_path=file_path,
            stored_content_hash=content_hash,
            stored_size=stat.st_size,
            stored_mtime=stat.st_mtime,
        )
        session.add(copy)
        session.commit()
        return document, copy
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass
```

**Should be:**
```python
def test_example(isolated_repo, create_scanned_document):
    doc, copy = create_scanned_document(isolated_repo, "test.pdf", "Content")
    # Use doc and copy in test
```

**Impact:** Eliminates ~240 lines of duplicate factory code

---

## 💡 Medium-Priority Recommendations

### 4. Parametrize Similar Tests (Est. ~210 lines savings)

**Opportunity 4a: test_path_security.py** (~80-100 lines saved)

**Current:** 20+ separate test methods for path validation
**Consolidate to:** 5 parametrized tests

```python
# Before: 3 separate tests
def test_reject_parent_directory_simple(self):
    with pytest.raises(PathSecurityError):
        validate_path_component("..")

def test_reject_parent_directory_in_path(self):
    with pytest.raises(PathSecurityError):
        validate_path_component("safe/../danger")

def test_reject_multiple_parent_references(self):
    with pytest.raises(PathSecurityError):
        validate_path_component("../../etc/passwd")

# After: 1 parametrized test
@pytest.mark.parametrize("invalid_path,description", [
    ("..", "simple parent directory"),
    ("safe/../danger", "parent in middle of path"),
    ("../../etc/passwd", "multiple parent references"),
    ("docs/../../../etc", "deep traversal attempt"),
])
def test_reject_parent_traversal(self, invalid_path, description):
    with pytest.raises(PathSecurityError, match="parent directory traversal"):
        validate_path_component(invalid_path)
```

**Other parametrization opportunities in this file:**
- Absolute path rejection (2 tests → 1 parametrized)
- Null byte rejection (2 tests → 1 parametrized)
- Invalid character tests (1 test with loop → parametrized)
- Security attack vectors (5 tests → 1 parametrized)

---

**Opportunity 4b: test_helpers.py** (~60 lines saved)

**Current:** 5 separate tests for operation regeneration scenarios
**Consolidate to:** 1 parametrized test

```python
@pytest.mark.parametrize("operation_attrs,current_hash,current_content,current_model,expected_regen,expected_reason", [
    # No operation case
    (None, "hash1", "content1", "model1", True, None),
    # Prompt hash changed
    ({"prompt_hash": "old", "document_content_hash": "c1", "model_name": "m1"},
     "new", "c1", "m1", True, "Prompt or model changed"),
    # Content hash changed
    ({"prompt_hash": "h1", "document_content_hash": "old", "model_name": "m1"},
     "h1", "new", "m1", True, "Document content changed"),
    # Model changed
    ({"prompt_hash": "h1", "document_content_hash": "c1", "model_name": "old"},
     "h1", "c1", "new", True, "Model changed"),
    # No changes
    ({"prompt_hash": "h1", "document_content_hash": "c1", "model_name": "m1"},
     "h1", "c1", "m1", False, None),
])
def test_operation_needs_regeneration(
    self, operation_attrs, current_hash, current_content, current_model,
    expected_regen, expected_reason
):
    """Test operation regeneration detection for various scenarios."""
    # ... implementation
```

---

**Opportunity 4c: test_file_operations.py** (~35 lines saved)

**Current:** 3 separate tests for conflict resolution strategies
**Consolidate to:** 1 parametrized test

```python
@pytest.mark.parametrize("resolution,should_raise,expected_behavior", [
    (ConflictResolution.SKIP, True, "raises FileConflictError"),
    (ConflictResolution.OVERWRITE, False, "replaces target file"),
    (ConflictResolution.RENAME, False, "creates target_1.txt"),
])
def test_conflict_resolution(self, tmp_path, resolution, should_raise, expected_behavior):
    """Test file move with different conflict resolution strategies."""
    # ... implementation
```

---

**Opportunity 4d: test_variable_patterns.py** (~25 lines saved)

**Current:** 6 tests for empty value validation
**Consolidate to:** 3 parametrized tests

```python
@pytest.mark.parametrize("empty_value", ["", "   "])
def test_empty_name_raises_error(self, tmp_path, empty_value):
    """Test that empty variable name raises ValueError."""
    with pytest.raises(ValueError, match="Variable name cannot be empty"):
        set_variable_pattern(tmp_path, empty_value, "Description")

@pytest.mark.parametrize("empty_value", ["", "   "])
def test_empty_description_raises_error(self, tmp_path, empty_value):
    """Test that empty description raises ValueError."""
    with pytest.raises(ValueError, match="Variable description cannot be empty"):
        set_variable_pattern(tmp_path, "year", empty_value)
```

---

## 📊 Impact Summary

| Priority | Recommendation | Files Affected | Lines Saved | Effort |
|----------|---------------|----------------|-------------|--------|
| **High** | Use db_session fixture | 6 | ~350 | Medium |
| **High** | Replace setup methods | 13 classes | ~200 | Medium |
| **High** | Use factory fixtures | 6 | ~240 | Medium |
| **Medium** | Parametrize path_security | 1 | ~80-100 | Low |
| **Medium** | Parametrize helpers | 1 | ~60 | Low |
| **Medium** | Parametrize file_operations | 1 | ~35 | Low |
| **Medium** | Parametrize variable_patterns | 1 | ~25 | Low |
| **TOTAL** | | **29 files/classes** | **~990-1010** | - |

---

## 🎯 Implementation Strategy

### Phase 1: Quick Wins (Low Effort, High Impact)
1. Parametrize test_path_security.py (~80-100 lines, 1-2 hours)
2. Parametrize test_helpers.py (~60 lines, 30 minutes)
3. Parametrize test_file_operations.py (~35 lines, 30 minutes)
4. Parametrize test_variable_patterns.py (~25 lines, 15 minutes)

**Total Phase 1:** ~200 lines saved, ~3-4 hours effort

### Phase 2: Fixture Migration (Medium Effort, Very High Impact)
1. Convert test_plan_integration.py to use fixtures (31 instances, ~150 lines saved)
2. Convert test_review_integration.py to use fixtures (23 instances, ~120 lines saved)
3. Convert remaining integration tests (~80 lines saved)

**Total Phase 2:** ~350 lines saved, ~8-10 hours effort

### Phase 3: Setup Method Consolidation (Medium Effort, High Impact)
1. Replace setup_repository() methods with shared fixtures/helpers (~200 lines saved)
2. Replace factory methods with shared fixtures (~240 lines saved)

**Total Phase 3:** ~440 lines saved, ~6-8 hours effort

---

## 📝 Best Practices for Future Test Development

### 1. Always Use Shared Fixtures
```python
# ✅ GOOD - Use shared fixtures
def test_example(isolated_repo, create_scanned_document, db_session):
    doc, copy = create_scanned_document(isolated_repo, "test.pdf")
    # Test logic here

# ❌ BAD - Don't create your own setup
def test_example(tmp_path):
    ensure_database()
    session_gen = get_session()
    session = next(session_gen)
    # ... duplicate setup code
```

### 2. Add Markers to All New Tests
```python
# ✅ GOOD - Mark all test classes
@pytest.mark.unit
class TestNewFeature:
    def test_something(self):
        pass

@pytest.mark.integration
@pytest.mark.slow  # If test is computationally intensive
class TestNewIntegration:
    def test_something(self):
        pass
```

### 3. Parametrize Similar Tests
```python
# ✅ GOOD - One parametrized test
@pytest.mark.parametrize("input,expected", [
    ("value1", "result1"),
    ("value2", "result2"),
    ("value3", "result3"),
])
def test_functionality(input, expected):
    assert process(input) == expected

# ❌ BAD - Multiple nearly-identical tests
def test_value1(self):
    assert process("value1") == "result1"

def test_value2(self):
    assert process("value2") == "result2"

def test_value3(self):
    assert process("value3") == "result3"
```

---

## 🔍 Useful Commands

### Run Tests by Marker
```bash
# Only unit tests (fast)
pytest -m unit

# Only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"

# Specific combinations
pytest -m "integration and not slow"
```

### Find Tests Needing Improvement
```bash
# Find files still using get_session() directly
grep -r "session_gen = get_session()" tests/integration/

# Find classes with setup_repository methods
grep -r "def setup_repository" tests/

# Find duplicate create_scanned_document methods
grep -r "def create_scanned_document" tests/
```

### Measure Test Performance
```bash
# Show slowest 20 tests
pytest --durations=20

# Show only slow tests
pytest --durations=0 -m slow
```

---

## 📚 References

- **Pytest Parametrize Documentation:** https://docs.pytest.org/en/stable/how-to/parametrize.html
- **Pytest Fixtures Documentation:** https://docs.pytest.org/en/stable/how-to/fixtures.html
- **Pytest Markers Documentation:** https://docs.pytest.org/en/stable/how-to/mark.html

---

## ✅ Progress Tracking

- [x] Phase 0: Analysis and Planning (COMPLETED 2025-11-15)
  - [x] Identify redundant tests (~260 lines)
  - [x] Find parametrization opportunities (~210 lines)
  - [x] Catalog duplicate setup patterns (~1000+ lines)
  - [x] Create shared fixtures in conftest.py
  - [x] Remove redundant tests
  - [x] Add pytest markers to all tests

- [ ] Phase 1: Parametrization (Est. 3-4 hours)
  - [ ] Parametrize test_path_security.py
  - [ ] Parametrize test_helpers.py
  - [ ] Parametrize test_file_operations.py
  - [ ] Parametrize test_variable_patterns.py

- [ ] Phase 2: Fixture Migration (Est. 8-10 hours)
  - [ ] Convert test_plan_integration.py
  - [ ] Convert test_review_integration.py
  - [ ] Convert remaining integration tests

- [ ] Phase 3: Setup Consolidation (Est. 6-8 hours)
  - [ ] Replace setup_repository() methods
  - [ ] Replace factory methods
  - [ ] Remove unused helper methods

**Total Estimated Effort:** 17-22 hours for ~1000 lines of savings
