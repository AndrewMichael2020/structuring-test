import builtins
import json
from pathlib import Path

import pytest

import store_artifacts as sa


def test_force_rebuild_artifacts_csv_no_op():
    """Test that force_rebuild_artifacts_csv works without errors (may be no-op if no artifacts)."""
    # This test just ensures the function can be called without errors
    result = sa.force_rebuild_artifacts_csv()
    assert isinstance(result, str)
    assert result  # Should return a path string
