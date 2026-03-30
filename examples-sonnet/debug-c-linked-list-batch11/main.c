#include <stdio.h>
#include "list.h"

int main() {
    Node* list = NULL;
    
    printf("Testing append operations:\n");
    append(&list, 10);
    append(&list, 20);
    append(&list, 30);
    print_list(list);
    
    printf("\nTesting prepend operation:\n");
    prepend(&list, 5);
    print_list(list);
    
    printf("\nList length: %d\n", get_length(list));
    
    printf("\nTesting find operation:\n");
    Node* found = find_node(list, 20);
    if (found) {
        printf("Found node with value: %d\n", found->data);
    }
    
    printf("\nTesting delete operation (delete 5):\n");
    delete_value(&list, 5);
    print_list(list);
    
    printf("\nTesting reverse operation:\n");
    reverse(&list);
    print_list(list);
    
    printf("\nFreeing list...\n");
    free_list(&list);
    printf("Done.\n");
    
    return 0;
}
