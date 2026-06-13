# ==========================================================================
# git-agent Production Docker Image
# ==========================================================================
# Build:  docker build -t git-agent .
# Run:    docker run --rm -v ~/.git-agent:/home/agent/.git-agent git-agent
# ==========================================================================

FROM python:3.11-slim AS base

# Metadata
LABEL maintainer="Super Z <superz@flux.fleet>"
LABEL description="FLUX Fleet Greenhorn Git-Agent — API-agnostic autonomous Git-native agent"
LABEL org.opencontainers.image.source="https://github.com/SuperInstance/git-agent"
LABEL org.opencontainers.image.license="MIT"

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 agent && \
    useradd --uid 1000 --gid agent --create-home --shell /bin/bash agent

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY src/ src/
COPY prompts/ prompts/
COPY onboarding/ onboarding/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[all]" 2>/dev/null || \
    pip install --no-cache-dir -e "."

# Change ownership to non-root user
RUN chown -R agent:agent /app

# Switch to non-root user
USER agent

# Default environment
ENV GIT_AGENT_CONFIG_PATH=/home/agent/.git-agent/config.yaml

# Health check — verify the agent can import and load config
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "from git_agent import Agent, load_config; print('OK')" || exit 1

# Entry point
ENTRYPOINT ["python", "-m", "git_agent"]
CMD ["--config", "/home/agent/.git-agent/config.yaml"]
