FROM ubuntu:24.04

RUN apt-get update && apt-get install -y tmux asciinema gcc g++ make valgrind gdb python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY linkedlist.c /app/
COPY linkedlist.h /app/
COPY main.c /app/
COPY Makefile /app/
COPY run-tests.sh /app/
RUN chmod +x /app/run-tests.sh