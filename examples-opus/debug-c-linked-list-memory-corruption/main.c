#include <stdio.h>
#include <stdlib.h>
#include "linkedlist.h"

int main() {
    Node* head = NULL;
    
    // Test insertions
    printf("Inserting elements...\n");
    insert_at_beginning(&head, 10);
    insert_at_beginning(&head, 20);
    insert_at_end(&head, 30);
    insert_at_end(&head, 40);
    
    printf("List after insertions: ");
    print_list(head);
    
    // Test deletion
    printf("\nDeleting 20...\n");
    delete_node(&head, 20);
    printf("List after deletion: ");
    print_list(head);
    
    // Test finding middle
    Node* middle = find_middle(head);
    if (middle) {
        printf("\nMiddle element: %d\n", middle->data);
    }
    
    // Test reverse
    printf("\nReversing list...\n");
    reverse_list(&head);
    printf("List after reversal: ");
    print_list(head);
    
    // Test cycle detection
    printf("\nChecking for cycle: %s\n", has_cycle(head) ? "Yes" : "No");
    
    // Clean up
    printf("\nFreeing list...\n");
    free_list(&head);
    
    return 0;
}