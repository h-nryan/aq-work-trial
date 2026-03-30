#ifndef LIST_H
#define LIST_H

typedef struct Node {
    int data;
    struct Node* next;
} Node;

Node* create_node(int data);
void append(Node** head, int data);
void prepend(Node** head, int data);
int delete_value(Node** head, int value);
int get_length(Node* head);
Node* find_node(Node* head, int value);
void reverse(Node** head);
void free_list(Node** head);
void print_list(Node* head);

#endif
