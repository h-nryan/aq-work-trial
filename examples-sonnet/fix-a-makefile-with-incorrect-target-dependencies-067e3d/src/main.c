#include <stdio.h>
#include "utils.h"

int main() {
    printf("Program starting...\n");
    
    int result = add_numbers(10, 20);
    printf("Result of add_numbers(10, 20): %d\n", result);
    
    result = multiply_numbers(5, 6);
    printf("Result of multiply_numbers(5, 6): %d\n", result);
    
    print_message("Hello from utils!");
    
    printf("Program finished successfully.\n");
    return 0;
}
