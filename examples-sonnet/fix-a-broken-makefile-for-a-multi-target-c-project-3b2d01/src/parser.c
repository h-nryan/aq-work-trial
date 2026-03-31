#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "parser.h"

void parse_input(const char* input) {
    printf("Parsing input: %s\n", input);
    
    char buffer[256];
    strncpy(buffer, input, sizeof(buffer) - 1);
    buffer[sizeof(buffer) - 1] = '\0';
    
    char* token = strtok(buffer, " ");
    int count = 0;
    
    while (token != NULL) {
        count++;
        printf("Token %d: %s\n", count, token);
        token = strtok(NULL, " ");
    }
    
    printf("Parsed %d tokens\n", count);
}

int parse_integer(const char* str) {
    return atoi(str);
}

double parse_double(const char* str) {
    return atof(str);
}
