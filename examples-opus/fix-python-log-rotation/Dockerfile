FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY log_rotator.py /app/
COPY config.json /app/
COPY test_logs/ /app/test_logs/
