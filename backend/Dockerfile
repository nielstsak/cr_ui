# Multi-stage build for Python with TA-Lib and scientific computing libs
FROM python:3.13-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download and compile TA-Lib C-Library
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Final image stage
FROM python:3.13-slim

WORKDIR /app

# Copy TA-Lib C-library headers and compiled binaries from builder stage
COPY --from=builder /usr/lib/libta_lib* /usr/lib/
COPY --from=builder /usr/include/ta-lib /usr/include/ta-lib

# Install runtime system packages (like libzmq for ZeroMQ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set python path
ENV PYTHONPATH=/app

# Setup entrypoint script
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
