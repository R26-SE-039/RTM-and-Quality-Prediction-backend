# syntax=docker/dockerfile:1

# RTM image WITH the code-coverage runner toolchains, so COVERAGE_ENABLED=true
# works in deployment:
#   - git: shallow-clones the analyzed repo
#   - default-jdk-headless + maven: Java coverage (JaCoCo via Maven/Gradle;
#     Gradle repos are expected to ship their own gradlew wrapper)
#   - nodejs + npm: JavaScript/TypeScript coverage (Jest / Mocha+nyc)
#   - chromium + chromium-driver: lets Selenium-based Java suites actually
#     launch a browser inside the container (tests must run headless)
# Python coverage needs nothing extra — the runner builds a venv from this
# image's own python3 and pip-installs pytest/pytest-cov per run.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        default-jdk-headless \
        maven \
        nodejs \
        npm \
        chromium \
        chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Debian puts the JDK under an arch-suffixed dir (java-17-openjdk-arm64/-amd64)
# that java_runner's candidate list doesn't include — point the runner at the
# arch-agnostic default-java symlink instead.
ENV JAVA_HOME_FOR_COVERAGE=/usr/lib/jvm/default-java

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
