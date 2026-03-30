#!/bin/bash

# Fix all the bugs in the linked list implementation
cat > linkedlist.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>
#include "linkedlist.h"

Node* create_node(int data) {
    Node* new_node = (Node*)malloc(sizeof(Node));
    new_node->data = data;
    new_node->next = NULL;
    return new_node;
}

void insert_at_beginning(Node** head, int data) {
    Node* new_node = create_node(data);
    new_node->next = *head;
    *head = new_node;
}

void insert_at_end(Node** head, int data) {
    Node* new_node = create_node(data);
    
    if (*head == NULL) {
        *head = new_node;
        return;
    }
    
    Node* temp = *head;
    while (temp->next != NULL) {
        temp = temp->next;
    }
    temp->next = new_node;
}

void delete_node(Node** head, int data) {
    if (*head == NULL) return;
    
    Node* temp = *head;
    
    if ((*head)->data == data) {
        *head = (*head)->next;
        free(temp);  // FIX: Added missing free
        return;
    }
    
    while (temp->next != NULL && temp->next->data != data) {
        temp = temp->next;
    }
    
    if (temp->next != NULL) {
        Node* node_to_delete = temp->next;
        temp->next = temp->next->next;
        free(node_to_delete);
    }
}

void reverse_list(Node** head) {
    Node* prev = NULL;
    Node* current = *head;
    Node* next = NULL;
    
    while (current != NULL) {
        next = current->next;
        current->next = prev;
        prev = current;
        current = next;  // FIX: Added missing line to advance current
    }
    
    *head = prev;
}

void print_list(Node* head) {
    Node* temp = head;
    while (temp != NULL) {
        printf("%d -> ", temp->data);
        temp = temp->next;
    }
    printf("NULL\n");
}

void free_list(Node** head) {
    Node* current = *head;
    Node* next;
    
    while (current != NULL) {
        next = current->next;
        free(current);
        current = next;  // FIX: Use next instead of current->next after free
    }
    
    *head = NULL;
}

Node* find_middle(Node* head) {
    if (head == NULL) return NULL;
    
    Node* slow = head;
    Node* fast = head;
    
    // FIX: Check both fast and fast->next to avoid segfault
    while (fast != NULL && fast->next != NULL) {
        slow = slow->next;
        fast = fast->next->next;
    }
    
    return slow;
}

int has_cycle(Node* head) {
    if (head == NULL) return 0;
    
    Node* slow = head;
    Node* fast = head;
    
    while (fast != NULL && fast->next != NULL) {
        slow = slow->next;
        fast = fast->next->next;
        
        if (slow == fast) {
            return 1;
        }
    }
    
    return 0;
}
EOF