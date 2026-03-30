# Bugs introduced (4 total, targeting 9 test functions)

## Bug 1: Memory leak in delete_node (line 40)
- Missing `free(temp)` after removing head node
- The old head is unlinked but never freed
- **Breaks**: test_delete_head_node (valgrind detects leak)

## Bug 2: Infinite loop in reverse_list (line 64)
- Missing `current = next` at end of while loop
- The loop variable never advances, causing infinite hang
- **Breaks**: test_reverse_list, test_reverse_single_element (timeout/hang)

## Bug 3: Use-after-free in free_list (line 87)
- After `free(current)`, accesses `current->next` instead of `next`
- Undefined behavior — may crash, corrupt heap, or appear to work
- **Breaks**: test_free_list, test_memory_cleanup

## Bug 4: Null pointer dereference in find_middle (line 101)
- Checks `fast->next != NULL` but not `fast != NULL`
- When list has even number of elements, `fast` becomes NULL and `fast->next` segfaults
- **Breaks**: test_find_middle_even, test_find_middle_odd (sometimes)
