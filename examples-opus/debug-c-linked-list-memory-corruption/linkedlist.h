#ifndef LINKEDLIST_H
#define LINKEDLIST_H

typedef struct Node {
    int data;
    struct Node* next;
} Node;

Node* create_node(int data);
void insert_at_beginning(Node** head, int data);
void insert_at_end(Node** head, int data);
void delete_node(Node** head, int data);
void reverse_list(Node** head);
void print_list(Node* head);
void free_list(Node** head);
Node* find_middle(Node* head);
int has_cycle(Node* head);

#endif