FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

WORKDIR /app

# Install deps in a separate layer so it's cached unless lockfile changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Copy application code
COPY . .

EXPOSE 8080

CMD ["uv", "run", "--frozen", "uvicorn", "agent_runner:app", "--host", "0.0.0.0", "--port", "8080"]
