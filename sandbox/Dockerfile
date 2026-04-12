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

# Create workspace and the 5 fixed project slot directories
RUN mkdir -p \
    /workspace/project_1 \
    /workspace/project_2 \
    /workspace/project_3 \
    /workspace/project_4 \
    /workspace/project_5
WORKDIR /workspace

# Keep container alive — agent sends commands via docker exec
CMD ["tail", "-f", "/dev/null"]
