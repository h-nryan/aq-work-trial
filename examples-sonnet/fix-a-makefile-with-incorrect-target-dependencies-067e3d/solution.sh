#!/bin/bash
set -euo pipefail

# Fix the Makefile with correct dependencies and phony declarations
cat > /app/Makefile << 'EOF'
# Fixed Makefile with correct dependencies and phony declarations

CC = gcc
CFLAGS = -Wall -Wextra -g

# Declare phony targets to avoid conflicts with files of the same name
.PHONY: all clean test

# 'all' should build the final executable
all: program
	@echo "Build complete"

# main.o depends on main.c and utils.h (since main.c includes utils.h)
main.o: src/main.c src/utils.h
	$(CC) $(CFLAGS) -c src/main.c -o main.o

# utils.o depends on utils.c and utils.h
utils.o: src/utils.c src/utils.h
	$(CC) $(CFLAGS) -c src/utils.c -o utils.o

# Link object files to create the executable
program: main.o utils.o
	$(CC) $(CFLAGS) main.o utils.o -o program

clean:
	rm -f *.o program

test: program
	./program
EOF
