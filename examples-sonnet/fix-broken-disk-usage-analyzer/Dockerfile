FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema curl python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY disk_analyzer.py /app/
RUN chmod +x /app/disk_analyzer.py
