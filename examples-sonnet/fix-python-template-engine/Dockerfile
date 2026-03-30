FROM python:3.12.7-slim

RUN apt-get update && apt-get install -y tmux asciinema curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY template_engine.py /app/
COPY templates/ /app/templates/
