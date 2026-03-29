FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt ./
COPY app.py ./
COPY data/ ./data/
