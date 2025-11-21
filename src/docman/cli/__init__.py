"""
docman - A CLI tool for organizing documents.

This package contains the CLI commands for docman, organized into separate modules
for better maintainability.
"""

import click

# Import command modules (not the commands themselves) to preserve module access
from docman.cli import (
    init as init_module,
    scan as scan_module,
    plan as plan_module,
    status as status_module,
    review as review_module,
    unmark as unmark_module,
    ignore as ignore_module,
    dedupe as dedupe_module,
    debug_prompt as debug_prompt_module,
    define as define_module,
    llm as llm_module,
    config as config_module,
    pattern as pattern_module,
)

# Import utilities for external use
from docman.cli.utils import (
    require_database,
    cleanup_orphaned_copies,
    find_duplicate_groups,
    detect_target_conflicts,
    detect_conflicts_in_operations,
    get_duplicate_summary,
)


@click.group()
@click.version_option(version="0.1.0", prog_name="docman")
def main() -> None:
    """docman - Organize documents using AI-powered tools."""
    pass


# Register individual commands
main.add_command(init_module.init)
main.add_command(scan_module.scan)
main.add_command(plan_module.plan)
main.add_command(status_module.status)
main.add_command(review_module.review)
main.add_command(unmark_module.unmark)
main.add_command(ignore_module.ignore)
main.add_command(dedupe_module.dedupe)
main.add_command(debug_prompt_module.debug_prompt)
main.add_command(define_module.define)

# Register command groups
main.add_command(llm_module.llm)
main.add_command(config_module.config)
main.add_command(pattern_module.pattern)

__all__ = [
    "main",
    "require_database",
    "cleanup_orphaned_copies",
    "find_duplicate_groups",
    "detect_target_conflicts",
    "detect_conflicts_in_operations",
    "get_duplicate_summary",
]
