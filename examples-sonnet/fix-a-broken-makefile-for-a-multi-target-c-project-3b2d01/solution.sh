#!/bin/bash
set -euo pipefail

# Create include directory and header files
mkdir -p /app/include

cat > /app/include/parser.h << 'EOF'
#ifndef PARSER_H
#define PARSER_H

void parse_input(const char* input);
int parse_integer(const char* str);
double parse_double(const char* str);

#endif
EOF

cat > /app/include/utils.h << 'EOF'
#ifndef UTILS_H
#define UTILS_H

double calculate_average(double a, double b, double c);
int sum_array(int* arr, int size);
double calculate_stddev(double* values, int count);

#endif
EOF

# Fix the Makefile
cat > /app/Makefile << 'EOF'
CC = gcc
CFLAGS = -Wall -Wextra -g -Iinclude

SRC_DIR = src
INC_DIR = include
OBJ_DIR = obj
BIN_DIR = bin

SOURCES = $(SRC_DIR)/main.c $(SRC_DIR)/parser.c $(SRC_DIR)/utils.c
OBJECTS = $(OBJ_DIR)/main.o $(OBJ_DIR)/parser.o $(OBJ_DIR)/utils.o
TARGET = $(BIN_DIR)/app

all: $(TARGET)

.PHONY: all clean test

$(OBJ_DIR)/main.o: $(SRC_DIR)/main.c $(INC_DIR)/parser.h $(INC_DIR)/utils.h
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(OBJ_DIR)/parser.o: $(SRC_DIR)/parser.c $(INC_DIR)/parser.h
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(OBJ_DIR)/utils.o: $(SRC_DIR)/utils.c $(INC_DIR)/utils.h
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET): $(OBJECTS)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) $(OBJECTS) -o $(TARGET) -lm

clean:
	rm -rf $(OBJ_DIR) $(BIN_DIR)

test: $(TARGET)
	$(TARGET)
EOF
