FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema \
    logrotate \
    bc \
    jq \
    gzip \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/log/samples /etc/logrotate.d/samples

COPY generate-samples.sh /app/

WORKDIR /app

RUN chmod +x /app/generate-samples.sh && \
    /app/generate-samples.sh
