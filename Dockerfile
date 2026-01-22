FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies (production only)
RUN uv sync --frozen --no-dev

# Copy application code
COPY src/ ./src/

# Runtime configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Run the application
CMD ["uv", "run", "python", "-m", "api"]
