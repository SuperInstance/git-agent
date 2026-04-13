# Code Quality Standards

> These are the non-negotiable code quality standards for all agents in the FLUX Fleet.
> Every line of code, every test, and every commit must meet these standards.

---

## General Principles

1. **Code is communication.** Your code will be read by other agents and humans. Write it to be
   understood, not just executed.
2. **Consistency over cleverness.** Follow existing patterns in the codebase. A boring, consistent
   solution is always preferred over a clever, novel one.
3. **No dead code.** Every line must serve a purpose. If it doesn't, delete it.
4. **Type everything.** Public APIs must have complete type hints. Internal code should too.
5. **Test everything.** If it's worth writing, it's worth testing.

---

## Python Standards

### Style

- Follow PEP 8. Use `ruff` or `flake8` for linting.
- Use `isort` for import sorting.
- Maximum line length: 100 characters.
- Use f-strings, not `.format()` or `%` formatting.
- Use `from __future__ import annotations` for modern type hint syntax.

### Type Hints

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

def process_tasks(
    tasks: List[Task],
    max_workers: int = 4,
    *,
    verbose: bool = False,
) -> Dict[str, bool]:
    """Process tasks in parallel.

    Parameters
    ----------
    tasks:
        List of tasks to process.
    max_workers:
        Maximum number of parallel workers.
    verbose:
        Enable verbose logging.

    Returns
    -------
    Dict[str, bool]
        Mapping of task ID to success status.
    """
    ...
```

### Documentation

- Every module has a docstring explaining its purpose (1-2 sentences).
- Every public class and function has a docstring.
- Use Google-style or NumPy-style docstrings (be consistent within a project).
- Docstrings must describe parameters, return types, and exceptions raised.

### Error Handling

- Use specific exception types, never bare `except:`.
- Use `logging` module, never `print()` for debug output.
- Define custom exception classes for domain-specific errors.
- Wrap external API calls in try/except with meaningful error messages.

### Anti-Patterns to Avoid

- `mutable default arguments` (e.g., `def foo(items: list = [])`)
- `star imports` (e.g., `from module import *`)
- `bare except` clauses
- `print()` for logging
- `os.system()` or `subprocess.call()` without proper error handling
- Deeply nested conditionals (use early returns instead)

---

## TypeScript Standards

### Style

- Follow the project's ESLint configuration. Default to strict rules.
- Use `interface` for object shapes, `type` for unions and intersections.
- Prefer `const` over `let`. Never use `var`.
- Use async/await, never raw `.then()` chains.
- Maximum line length: 100 characters.

### Type Safety

```typescript
interface Task {
  id: string;
  description: string;
  priority: "critical" | "high" | "medium" | "low";
  effort: "low" | "medium" | "high";
}

async function executeTask(task: Task, opts?: ExecutionOptions): Promise<TaskResult> {
  // Implementation
}
```

- Enable `strict: true` in `tsconfig.json`.
- No `any` types unless absolutely necessary (and document why).
- Use generics for reusable utilities.
- Define return types on all public functions.

### Error Handling

- Use typed error classes.
- Never swallow errors silently.
- Use proper error boundaries in frontend code.

---

## Rust Standards

### Style

- Follow `rustfmt` defaults.
- Use `clippy` with default lints enabled.
- Prefer idiomatic Rust: pattern matching, `Option`/`Result`, iterators.
- No `unwrap()` in production code (except in tests).

### Error Handling

```rust
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AgentError {
    #[error("Configuration error: {0}")]
    Config(String),
    #[error("GitHub API error: {0}")]
    GitHub(#[from] github::Error),
    #[error("Task {task_id} failed: {reason}")]
    TaskFailed { task_id: String, reason: String },
}

pub fn execute(task: &Task) -> Result<TaskResult, AgentError> {
    // Implementation using ? operator
}
```

- Define custom error enums with `thiserror`.
- Use `?` operator for error propagation.
- Handle errors explicitly; never `panic!` in library code.

---

## Test Requirements

### Minimum Thresholds

- **15 tests per feature.** This is a hard minimum. A "feature" is any self-contained unit of
  work: a new module, a significant refactoring, or a new capability.
- **100% coverage on critical paths.** Auth, payment, data integrity — these paths must be
  fully covered. Use `coverage.py` or equivalent to verify.

### Test Structure

```python
class TestFeatureName:
    """Comprehensive tests for the FeatureName module."""

    def test_happy_path_basic_usage(self):
        """The most common use case should work correctly."""
        ...

    def test_edge_case_empty_input(self):
        """Empty input should be handled gracefully."""
        ...

    def test_error_case_invalid_input_raises(self):
        """Invalid input should raise a descriptive exception."""
        ...

    def test_boundary_condition_max_size(self):
        """Behavior at maximum allowed size should be correct."""
        ...

    def test_integration_with_related_module(self):
        """Feature should integrate correctly with dependent modules."""
        ...
```

### Test Categories

Every feature should include tests in these categories:

1. **Happy path** — Normal usage, expected inputs (2-3 tests).
2. **Edge cases** — Empty inputs, single items, boundary values (3-4 tests).
3. **Error cases** — Invalid inputs, missing data, permission errors (3-4 tests).
4. **Integration** — Interaction with other modules/services (2-3 tests).
5. **Performance** — Basic timing/scale checks for data-intensive features (1-2 tests).

### Test Quality Standards

- Test names must be descriptive. `test_config_missing_api_key_raises` not `test_2`.
- Tests must be independent. No test should depend on another test's state.
- Use fixtures for common setup. Use factories for test data.
- Mock external services (GitHub API, LLM providers). Never hit real APIs in tests.
- Assert specific values, not just "no exception raised."

---

## Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description> [T-XXX]

<body>
```

### Types

| Type       | Usage                                                    |
|------------|----------------------------------------------------------|
| `feat`     | New feature or capability                                |
| `fix`      | Bug fix                                                  |
| `docs`     | Documentation changes only                               |
| `style`    | Code style changes (formatting, semicolons, etc.)        |
| `refactor` | Code restructuring without behavior change               |
| `test`     | Adding or updating tests                                 |
| `chore`    | Build process, dependencies, tooling                    |
| `perf`     | Performance improvements                                 |
| `ci`       | CI/CD configuration changes                              |

### Examples

```
feat(auth): implement JWT token validation [T-042]
fix(github): handle rate limit errors gracefully [T-043]
test(config): add 18 tests for config wizard validation [T-044]
docs(readme): comprehensive rewrite with architecture diagram
refactor(llm): extract provider interface into protocol [T-045]
```

### Rules

- Subject line: maximum 72 characters.
- Body: explain *what* and *why*, not *how*.
- Reference task ID with `[T-XXX]` when applicable.
- One logical change per commit.

---

## Pull Request Title Format

```
[T-XXX] Brief description of the change
```

### Examples

```
[T-042] Implement JWT token validation for API endpoints
[T-043] Fix GitHub rate limit handling in fleet communicator
[T-044] Add comprehensive config wizard with validation
```

### PR Description Template

```markdown
## Summary

Brief description of what this PR does and why.

## Changes

- List of concrete changes made
- With file paths where relevant

## Testing

- 15+ tests added/updated
- All tests pass: `pytest -v`
- Coverage: XX%

## Task Reference

Resolves T-XXX

## Breaking Changes

None / Description of any breaking changes

## Screenshots / Output

Relevant output or screenshots demonstrating the change.
```

---

## README Standards

Every project repository must have a `README.md` that includes:

1. **Project name and tagline** — One sentence describing what this is.
2. **What** — Detailed description of the project (150+ words).
3. **Why** — The motivation and problem being solved.
4. **Architecture** — High-level diagram or description of how components fit together.
5. **Quick Start** — Step-by-step instructions to get running in under 5 minutes.
6. **Configuration** — All configurable options with descriptions and defaults.
7. **Development** — How to set up a dev environment, run tests, contribute.
8. **API Reference** — For libraries: list all public functions/classes with brief descriptions.
9. **License** — SPDX identifier at minimum.

### README Depth

- **Minimum 150 words per major section.** The Quick Start, Configuration, and What sections
  must each contain at least 150 words of substantive content.
- No placeholder sections. If a section isn't applicable, remove it.
- Include working code examples, not pseudocode.
- Keep the README updated with every significant change.

---

## Documentation Depth Requirements

### Inline Documentation

- Every public function, class, and module has a docstring.
- Docstrings describe: purpose, parameters (with types), return value, exceptions.
- Complex logic gets inline comments explaining *why*.
- No TODO/FIXME without an associated issue number.

### External Documentation

- User-facing documentation in Markdown, co-located with the code.
- Architecture Decision Records (ADRs) for significant design choices.
- Changelog maintained with every release (CHANGELOG.md).
- API reference generated from docstrings where possible.

### Minimum Content Thresholds

| Document Type          | Minimum Word Count | Notes                           |
|------------------------|--------------------|----------------------------------|
| README.md              | 500+ words         | Per-project                      |
| README section         | 150+ words         | Major sections                   |
| ADR                    | 200+ words         | Context, decision, consequences  |
| Module docstring       | 30+ words          | Purpose and key abstractions     |
| Function docstring     | 20+ words          | Beyond parameter listing         |
| CHANGELOG entry        | 30+ words          | Per-version entry                |

---

## Code Review Checklist

Before opening a PR, verify:

- [ ] All new code has type hints
- [ ] All new public functions have docstrings
- [ ] 15+ tests added for new features
- [ ] All tests pass (`pytest -v`)
- [ ] No `print()` statements or hardcoded secrets
- [ ] Conventional commit messages with task IDs
- [ ] PR title follows `[T-XXX] Description` format
- [ ] README updated if user-facing changes
- [ ] No lint errors (`ruff check .` or equivalent)
- [ ] Error handling is explicit and meaningful
