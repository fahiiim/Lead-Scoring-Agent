"""Initialize the lead scoring service project structure.

The initializer is intentionally idempotent. It creates missing directories and
empty files but never overwrites existing content.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DIRECTORIES = (
    "app/api/v1",
    "app/agents",
    "app/core",
    "app/db",
    "app/models",
    "app/providers",
    "app/repositories",
    "app/research",
    "app/schemas",
    "app/scoring",
    "app/services",
    "app/utils",
    "alembic/versions",
    "tests/integration",
    "tests/unit",
)

FILES = (
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "README.md",
    "alembic.ini",
    "alembic/env.py",
    "alembic/script.py.mako",
    "alembic/versions/20260830_0001_initial.py",
    "app/__init__.py",
    "app/main.py",
    "app/api/__init__.py",
    "app/api/dependencies.py",
    "app/api/v1/__init__.py",
    "app/api/v1/routes.py",
    "app/agents/__init__.py",
    "app/agents/extractor.py",
    "app/agents/rule_based.py",
    "app/core/__init__.py",
    "app/core/config.py",
    "app/core/exceptions.py",
    "app/core/logging.py",
    "app/core/middleware.py",
    "app/db/__init__.py",
    "app/db/base.py",
    "app/db/models.py",
    "app/models/__init__.py",
    "app/models/domain.py",
    "app/providers/__init__.py",
    "app/providers/public_data.py",
    "app/providers/search.py",
    "app/providers/website.py",
    "app/providers/wikidata.py",
    "app/repositories/__init__.py",
    "app/repositories/leads.py",
    "app/research/__init__.py",
    "app/research/base.py",
    "app/research/orchestrator.py",
    "app/schemas/__init__.py",
    "app/schemas/lead.py",
    "app/scoring/__init__.py",
    "app/scoring/engine.py",
    "app/scoring/profile.py",
    "app/services/__init__.py",
    "app/services/lead_service.py",
    "app/utils/__init__.py",
    "app/utils/cache.py",
    "app/utils/urls.py",
    "pyproject.toml",
    "render.yaml",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/integration/__init__.py",
    "tests/integration/test_api.py",
    "tests/integration/test_orchestrator.py",
    "tests/integration/test_repository.py",
    "tests/integration/test_website_provider.py",
    "tests/unit/__init__.py",
    "tests/unit/test_cache.py",
    "tests/unit/test_config.py",
    "tests/unit/test_evidence.py",
    "tests/unit/test_extractor.py",
    "tests/unit/test_public_data.py",
    "tests/unit/test_search.py",
    "tests/unit/test_scoring.py",
    "tests/unit/test_urls.py",
)


def initialize() -> None:
    """Create the project skeleton without replacing existing files."""
    for relative_directory in DIRECTORIES:
        (PROJECT_ROOT / relative_directory).mkdir(parents=True, exist_ok=True)

    for relative_file in FILES:
        path = PROJECT_ROOT / relative_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)


if __name__ == "__main__":
    initialize()
