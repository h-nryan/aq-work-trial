CC = gcc
CFLAGS = -Wall -g -O0
TARGET = linkedlist_program

all: $(TARGET)

$(TARGET): main.o linkedlist.o
	$(CC) $(CFLAGS) -o $(TARGET) main.o linkedlist.o

main.o: main.c linkedlist.h
	$(CC) $(CFLAGS) -c main.c

linkedlist.o: linkedlist.c linkedlist.h
	$(CC) $(CFLAGS) -c linkedlist.c

clean:
	rm -f *.o $(TARGET)

.PHONY: all clean