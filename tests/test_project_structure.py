"""Test project structure and setup."""

from pathlib import Path


def test_project_directories_exist():
    """Project should have all required directories for development."""
    project_root = Path(__file__).parent.parent

    # Python package should exist with __init__.py
    package_dir = project_root / "aviation_anomaly"
    assert package_dir.exists(), "aviation_anomaly package directory should exist"
    assert package_dir.is_dir(), "aviation_anomaly should be a directory"
    assert (package_dir / "__init__.py").exists(), "Package should have __init__.py to be importable"

    # Required directories should exist
    required_dirs = ["sql", "data", "static", "tests"]
    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        assert dir_path.exists(), f"{dir_name}/ directory should exist"
        assert dir_path.is_dir(), f"{dir_name} should be a directory"


def test_gitignore_excludes_critical_patterns():
    """Git should ignore generated files and sensitive data."""
    project_root = Path(__file__).parent.parent
    gitignore = project_root / ".gitignore"

    assert gitignore.exists(), ".gitignore file should exist"

    content = gitignore.read_text()

    # Patterns that must be ignored for clean repository
    critical_patterns = [
        "__pycache__",  # Python bytecode cache
        "*.pyc",  # Compiled Python files
        "data/",  # Data directory (may contain large/sensitive files)
        ".env",  # Environment variables with secrets
        ".venv/",  # Virtual environment
    ]

    for pattern in critical_patterns:
        assert pattern in content, f".gitignore should contain pattern: {pattern}"
