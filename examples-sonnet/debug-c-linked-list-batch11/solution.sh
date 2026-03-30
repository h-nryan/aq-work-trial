#!/bin/bash
set -euo pipefail

# Fix all bugs in the linked list implementation
cat > /app/list.c << 'EOF'
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
    
    // FIX BUG 1: Free the deleted head node
    if ((*head)->data == value) {
        Node* temp = *head;
        *head = (*head)->next;
        free(temp);
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
        current = next;
    }
    
    *head = prev;
}

void free_list(Node** head) {
    Node* current = *head;
    
    while (current != NULL) {
        Node* next = current->next;
        free(current);
        current = next;
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
EOF
