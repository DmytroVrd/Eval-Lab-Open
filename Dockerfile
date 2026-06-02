FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY . .

RUN python -m pip install --upgrade pip \
    && if [ -f pyproject.toml ]; then \
        python -m pip install -e ".[dev]" || python -m pip install -e .; \
    elif [ -f requirements.txt ]; then \
        python -m pip install -r requirements.txt; \
    else \
        python -m pip install fastapi "uvicorn[standard]" sqlalchemy aiosqlite alembic pydantic-settings httpx; \
    fi

RUN mkdir -p data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn ${APP_MODULE:-app.main:app} --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8000}"]
