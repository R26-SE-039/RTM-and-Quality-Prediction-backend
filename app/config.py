from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for environment-driven configuration.

    Values are loaded from backend/.env (falling back to real environment
    variables) at process startup — nothing reads os.environ directly
    elsewhere in the app.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", str_strip_whitespace=True
    )

    github_username: str = ""
    github_token: str = ""
    # When false, the code-coverage runners (Java/Maven+JaCoCo, JS, Python)
    # are turned off and POST /api/coverage/analyze returns 503. Set
    # COVERAGE_ENABLED=false in deployments whose image doesn't ship the
    # build toolchains (e.g. the small AWS box). Defaults to true so local
    # dev is unchanged.
    coverage_enabled: bool = True
    coverage_job_timeout_seconds: int = 300
    # Optional: force a specific JDK for Java coverage runs (Maven/Gradle +
    # JaCoCo), overriding the auto-detected one. Useful if the backend host's
    # default `java` is a version JaCoCo can't instrument (e.g. a preview
    # build) and none of the auto-detected candidates are right either.
    java_home_for_coverage: str = ""

    @property
    def github_credentials_configured(self) -> bool:
        return bool(self.github_username.strip() and self.github_token.strip())


settings = Settings()
