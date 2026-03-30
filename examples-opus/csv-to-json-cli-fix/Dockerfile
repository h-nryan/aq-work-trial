FROM python:3.12.7-slim

RUN apt-get update && apt-get install -y tmux asciinema curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY csv_to_json.py /app/
COPY inputs /app/inputs
