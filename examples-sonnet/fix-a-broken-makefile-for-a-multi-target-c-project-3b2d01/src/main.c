#include <stdio.h>
#include "parser.h"
#include "utils.h"

int main() {
    printf("Starting application...\n");
    
    const char* input = "42 3.14 hello";
    parse_input(input);
    
    double result = calculate_average(10.5, 20.3, 15.7);
    printf("Average: %.2f\n", result);
    
    int sum = sum_array((int[]){1, 2, 3, 4, 5}, 5);
    printf("Sum: %d\n", sum);
    
    printf("Application finished successfully.\n");
    return 0;
}
