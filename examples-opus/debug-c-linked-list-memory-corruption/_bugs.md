# Bugs introduced (4 total, targeting 9 test functions)
# Difficulty: LEARNABLE (Opus 1/5) — bugs are subtle, memory-related

## Bug 1: Memory leak in delete_node (line 40)
- Missing `free(temp)` after removing head node
- The old head is unlinked but never freed
- **Subtlety**: MODERATE — the deletion logic looks correct at first glance
  (node is properly unlinked), but the missing free is a classic C oversight.
  Agent must think about memory management, not just pointer manipulation.
- **Breaks**: test_delete_head_node (valgrind detects leak)

## Bug 2: Infinite loop in reverse_list (line 64)
- Missing `current = next` at end of while loop
- The loop variable never advances, causing infinite hang
- **Subtlety**: HIGH — the three pointer variables (prev, current, next) make
  the loop look correct on quick reading. The missing advancement is easy to
  overlook because the other two assignments are present. Causes timeout, not
  a clear error message — agent must reason about why the program hangs.
- **Breaks**: test_reverse_list, test_reverse_single_element (timeout/hang)

## Bug 3: Use-after-free in free_list (line 87)
- After `free(current)`, accesses `current->next` instead of the saved `next`
- Undefined behavior — may crash, corrupt heap, or silently appear to work
- **Subtlety**: HIGH — the `next` variable IS saved correctly on the previous
  line, but the wrong variable is used on the next line. The bug is a single
  wrong variable name (`current->next` vs `next`). Undefined behavior means
  symptoms are unpredictable — sometimes works, sometimes crashes.
- **Breaks**: test_free_list, test_memory_cleanup

## Bug 4: Null pointer dereference in find_middle (line 101)
- Checks `fast->next != NULL` but not `fast != NULL` first
- When list has even number of elements, `fast` becomes NULL and `fast->next` segfaults
- **Subtlety**: MODERATE — classic two-pointer algorithm bug. The correct
  condition (`fast != NULL && fast->next != NULL`) is a well-known pattern,
  but missing the first check is easy when focused on the algorithm logic.
- **Breaks**: test_find_middle_even, test_find_middle_odd (sometimes)

## Why this is learnable (not too easy, not too hard):
- Bugs involve C memory semantics (use-after-free, missing free, null deref)
  which require deeper understanding than simple logic errors
- Bug 2 and 3 are genuinely subtle — correct-looking code with one wrong variable
- Bug symptoms are indirect (hangs, undefined behavior) rather than clear errors
- Opus solves it 20% of the time — agents that don't carefully trace pointer
  operations will miss Bug 2 or 3
