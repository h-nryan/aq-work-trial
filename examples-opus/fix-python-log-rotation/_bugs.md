# Bugs introduced (6 total, targeting 8 test functions)
# Difficulty: LEARNABLE (Opus 2/5) — mix of subtle and moderate bugs

## Bug 1: Wrong unit in file size calculation (line 17)
- `get_file_size()` divides by 1024, returning KB instead of bytes
- `should_rotate()` then compares KB against a bytes threshold
- **Subtlety**: LOW-MODERATE — the division by 1024 is visible, but the
  mismatch only becomes apparent when tracing through should_rotate().
  Agent must notice the unit inconsistency across two functions.
- **Breaks**: test_file_size_calculation, test_rotation_triggers_correctly

## Bug 2: Text mode for binary operation (line 33)
- `compress_file()` opens source in text mode ('r') but gzip.open expects bytes ('wb')
- Writing a string to a bytes file raises TypeError
- **Subtlety**: MODERATE — the mode mismatch ('r' vs 'wb') is a common Python
  gotcha. The error only surfaces when compression is actually triggered.
- **Breaks**: test_compression_works_correctly

## Bug 3: Missing directory in rotated path (line 48)
- Rotated filename uses only basename, losing the directory path
- File gets created in current working directory instead of the log directory
- **Subtlety**: MODERATE — `os.path.basename()` is correct for getting the
  filename, but using it without the directory for the destination path is
  wrong. Agent must notice the path construction, not just the filename logic.
- **Breaks**: test_rotated_filename_preserves_extension, test_full_rotation_workflow

## Bug 4: Uncompressed file not removed after compression (line 60)
- After gzip compression, the original uncompressed rotated file is left behind
- **Subtlety**: LOW — a missing cleanup step. Easy to spot if reading carefully.
- **Breaks**: test_compressed_files_handled_in_rotation

## Bug 5: Incorrect rotated file detection (line 77)
- cleanup_old_logs doesn't account for .gz extension in rotated files
- **Subtlety**: MODERATE — requires understanding the file naming convention
  and how compression changes file extensions.
- **Breaks**: test_multiple_rotations_with_max_backups

## Bug 6: Wrong sort order for cleanup (line 81)
- Sorts alphabetically instead of by modification time
- Deletes wrong files when enforcing retention policy
- **Subtlety**: HIGH — alphabetical sort APPEARS to work for timestamps in
  filenames, but fails when the timestamp format doesn't sort lexicographically
  or when mixed .gz and non-.gz files are present.
- **Breaks**: test_multiple_rotations_with_max_backups

## Why this is learnable (not too easy, not too hard):
- Mix of easy bugs (Bug 4) and subtle bugs (Bug 6) means an agent can
  make progress but may not fix everything
- Bugs span multiple methods — agent must read the whole class
- Some bugs interact (Bug 3 affects cleanup path in Bug 5/6)
- Opus solves it 40% of the time — gets most bugs but often misses Bug 5 or 6
