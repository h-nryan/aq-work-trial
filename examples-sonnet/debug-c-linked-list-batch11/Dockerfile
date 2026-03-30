FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema gcc valgrind python3 python3-pip curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY list.c /app/
COPY list.h /app/
COPY main.c /app/
COPY Makefile /app/
