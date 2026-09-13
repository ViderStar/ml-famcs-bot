# Контекст сборки — корень проекта: нужны и bot/, и checker/ (mlcheck ставится
# как путь-зависимость).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY checker/ /app/checker/
COPY bot/pyproject.toml bot/uv.lock* /app/bot/
COPY bot/src/ /app/bot/src/
# Вымышленные студенты для проверки экранов: маленькие и целиком выдуманные,
# поэтому едут в образ, а не монтируются снаружи.
COPY bot/demo/ /app/bot/demo/

WORKDIR /app/bot
RUN uv sync --no-dev

# Данные курса монтируются снаружи только на чтение, состояние бота — в /state.
ENV DATA_ROOT=/data \
    DB_PATH=/state/mlbot.sqlite3
VOLUME ["/state"]

CMD ["uv", "run", "--no-dev", "mlbot"]
