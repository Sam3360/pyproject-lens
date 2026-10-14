"""Public API for pyproject-lens."""

from .analyzers import MAX_FILES, MAX_SCAN_DEPTH, analyze
from .fixes import apply_safe_fixes
from .models import Finding, Report, Section

__all__ = ["MAX_FILES", "MAX_SCAN_DEPTH", "analyze", "apply_safe_fixes", "Finding", "Report", "Section"]
__version__ = "0.7.0"
