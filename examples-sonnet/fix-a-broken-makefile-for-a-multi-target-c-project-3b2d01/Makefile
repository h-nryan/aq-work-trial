CC = gcc
CFLAGS = -Wall -Wextra -g -Iinclude

SRC_DIR = src
INC_DIR = include
OBJ_DIR = obj
BIN_DIR = bin

SOURCES = $(SRC_DIR)/main.c $(SRC_DIR)/parser.c $(SRC_DIR)/utils.c
OBJECTS = $(OBJ_DIR)/main.o $(OBJ_DIR)/parser.o $(OBJ_DIR)/utils.o
TARGET = $(BIN_DIR)/app

# BUG: Missing .PHONY declaration - targets won't work if files named 'all', 'clean', or 'test' exist
all: $(TARGET)

$(OBJ_DIR)/main.o: $(SRC_DIR)/main.c $(INC_DIR)/parser.h $(INC_DIR)/utils.h
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

# BUG: Missing header dependency - parser.o won't rebuild when parser.h changes
$(OBJ_DIR)/parser.o: $(SRC_DIR)/parser.c
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

# BUG: Wrong source file 'helper.c' doesn't exist - should be 'utils.c'
$(OBJ_DIR)/utils.o: $(SRC_DIR)/helper.c $(INC_DIR)/utils.h
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $(SRC_DIR)/utils.c -o $@

# BUG: Missing -lm linker flag - sqrt() function requires math library
$(TARGET): $(OBJECTS)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) $(OBJECTS) -o $(TARGET)

clean:
	rm -rf $(OBJ_DIR) $(BIN_DIR)

test: $(TARGET)
	$(TARGET)
