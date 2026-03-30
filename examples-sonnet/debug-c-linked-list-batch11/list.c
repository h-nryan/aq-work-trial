#include <stdio.h>
#include <stdlib.h>
#include "list.h"

Node* create_node(int data) {
    Node* node = (Node*)malloc(sizeof(Node));
    if (node == NULL) {
        return NULL;
    }
    node->data = data;
    node->next = NULL;
    return node;
}

void append(Node** head, int data) {
    Node* new_node = create_node(data);
    if (new_node == NULL) {
        return;
    }
    
    if (*head == NULL) {
        *head = new_node;
        return;
    }
    
    Node* current = *head;
    while (current->next != NULL) {
        current = current->next;
    }
    current->next = new_node;
}

void prepend(Node** head, int data) {
    Node* new_node = create_node(data);
    if (new_node == NULL) {
        return;
    }
    
    new_node->next = *head;
    *head = new_node;
}

int delete_value(Node** head, int value) {
    if (*head == NULL) {
        return 0;
    }
    
    // BUG 1: Memory leak when deleting head node
    // Missing free() for the deleted head node
    if ((*head)->data == value) {
        Node* temp = *head;
        *head = (*head)->next;
        // Missing: free(temp);
        return 1;
    }
    
    Node* current = *head;
    while (current->next != NULL) {
        if (current->next->data == value) {
            Node* temp = current->next;
            current->next = current->next->next;
            free(temp);
            return 1;
        }
        current = current->next;
    }
    
    return 0;
}

int get_length(Node* head) {
    int count = 0;
    Node* current = head;
    while (current != NULL) {
        count++;
        current = current->next;
    }
    return count;
}

Node* find_node(Node* head, int value) {
    Node* current = head;
    while (current != NULL) {
        if (current->data == value) {
            return current;
        }
        current = current->next;
    }
    return NULL;
}

void reverse(Node** head) {
    Node* prev = NULL;
    Node* current = *head;
    Node* next = NULL;
    
    while (current != NULL) {
        next = current->next;
        current->next = prev;
        prev = current;
        // BUG 2: Missing advancement of current pointer
        // This causes an infinite loop
        // Missing: current = next;
    }
    
    *head = prev;
}

void free_list(Node** head) {
    Node* current = *head;
    
    while (current != NULL) {
        Node* next = current->next;
        free(current);
        // BUG 3: Use-after-free
        // Accessing current->next after freeing current
        current = current->next;  // Should be: current = next;
    }
    
    *head = NULL;
}

void print_list(Node* head) {
    Node* current = head;
    while (current != NULL) {
        printf("%d", current->data);
        if (current->next != NULL) {
            printf(" -> ");
        }
        current = current->next;
    }
    printf("\n");
}
