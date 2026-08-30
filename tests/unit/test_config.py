from __future__ import annotations

from app.core.config import Settings


def test_blank_optional_environment_values_are_unset() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="",
        database_url=" ",
        search_base_url="",
        search_api_key="",
        sec_user_agent="",
        target_min_employees="",
        target_max_employees=" ",
    )

    assert settings.openai_api_key is None
    assert settings.database_url is None
    assert settings.search_base_url is None
    assert settings.search_api_key is None
    assert settings.sec_user_agent is None
    assert settings.target_min_employees is None
    assert settings.target_max_employees is None
