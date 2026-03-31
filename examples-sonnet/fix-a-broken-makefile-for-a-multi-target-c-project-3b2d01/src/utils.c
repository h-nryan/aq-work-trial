#include <stdio.h>
#include <math.h>
#include "utils.h"

double calculate_average(double a, double b, double c) {
    return (a + b + c) / 3.0;
}

int sum_array(int* arr, int size) {
    int sum = 0;
    for (int i = 0; i < size; i++) {
        sum += arr[i];
    }
    return sum;
}

double calculate_stddev(double* values, int count) {
    if (count <= 0) return 0.0;
    
    double mean = 0.0;
    for (int i = 0; i < count; i++) {
        mean += values[i];
    }
    mean /= count;
    
    double variance = 0.0;
    for (int i = 0; i < count; i++) {
        double diff = values[i] - mean;
        variance += diff * diff;
    }
    variance /= count;
    
    return sqrt(variance);
}
