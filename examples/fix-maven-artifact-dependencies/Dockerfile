FROM ubuntu:24.04

WORKDIR /app

RUN mkdir -p /logs && chmod 777 /logs

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY CMakeLists.txt /app/CMakeLists.txt
COPY libs /app/lib
COPY app /app/app

COPY applypatch /app/applypatch
COPY applypatch.sh /app/applypatch.sh
RUN chmod +x /app/applypatch /app/applypatch.sh && \
    ln -sf /app/applypatch /usr/local/bin/applypatch && \
    ln -sf /app/applypatch.sh /usr/local/bin/applypatch.sh
