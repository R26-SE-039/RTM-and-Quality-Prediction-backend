# syntax=docker/dockerfile:1

# API-only RTM image: the code-coverage runners (Java/Maven+JaCoCo, JS, Python)
# are intentionally NOT installed here — coverage is disabled in this deployment
# via COVERAGE_ENABLED=false, so the image stays small. All Python deps are
# manylinux wheels (psycopg2-binary bundles libpq), so no build toolchain is
# needed.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
