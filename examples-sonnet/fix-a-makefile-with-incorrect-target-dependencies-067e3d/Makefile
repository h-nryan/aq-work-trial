# Buggy Makefile with incorrect dependencies and missing phony declarations

CC = gcc
CFLAGS = -Wall -Wextra -g

# BUG 1: Missing .PHONY declarations for non-file targets
# This causes issues when files named 'clean', 'test', or 'all' exist

# BUG 2: Incorrect target dependencies
# 'all' should depend on the final executable, not object files
all: main.o utils.o
	@echo "Build complete"

# BUG 3: Missing dependency on header file
# main.o should depend on utils.h, but it's not listed
main.o: src/main.c
	$(CC) $(CFLAGS) -c src/main.c -o main.o

# BUG 4: Wrong source file dependency
# utils.o depends on src/utils.c, not src/helper.c
utils.o: src/helper.c src/utils.h
	$(CC) $(CFLAGS) -c src/utils.c -o utils.o

# Target missing from 'all' dependencies
program: main.o utils.o
	$(CC) $(CFLAGS) main.o utils.o -o program

clean:
	rm -f *.o program

test: program
	./program
