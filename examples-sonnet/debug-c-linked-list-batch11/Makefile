CC = gcc
CFLAGS = -Wall -Wextra -g -O0
TARGET = list_program

all: $(TARGET)

$(TARGET): main.o list.o
	$(CC) $(CFLAGS) -o $(TARGET) main.o list.o

main.o: main.c list.h
	$(CC) $(CFLAGS) -c main.c

list.o: list.c list.h
	$(CC) $(CFLAGS) -c list.c

clean:
	rm -f *.o $(TARGET)

.PHONY: all clean
