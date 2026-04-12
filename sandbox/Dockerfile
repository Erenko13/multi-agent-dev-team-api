FROM python:3.12-slim

# Install Node.js 20, npm, and common build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        git \
        build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace

# Keep container alive — agent sends commands via docker exec
CMD ["tail", "-f", "/dev/null"]
