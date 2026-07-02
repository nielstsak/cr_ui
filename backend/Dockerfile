# Multi-stage build for Python with TA-Lib
FROM python:3.13-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

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

COPY --from=builder /usr/lib/libta_lib* /usr/lib/
COPY --from=builder /usr/include/ta-lib /usr/include/ta-lib

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier uniquement les fichiers nécessaires
COPY backend/requirements.txt .
COPY backend/vectorbtpro_package/ ./backend/vectorbtpro_package/

RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source dans le dossier backend
COPY backend/ ./backend/

# Set python path
ENV PYTHONPATH=/app

# Setup entrypoint script
RUN chmod +x backend/entrypoint.sh

ENTRYPOINT ["/app/backend/entrypoint.sh"]