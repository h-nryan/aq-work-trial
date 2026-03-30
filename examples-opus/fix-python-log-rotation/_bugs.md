# Bugs introduced (6 total, targeting 8 test functions)

## Bug 1: Wrong unit in file size calculation (line 17)
- `get_file_size()` divides by 1024, returning KB instead of bytes
- `should_rotate()` then compares KB against a bytes threshold
- **Breaks**: test_file_size_calculation, test_rotation_triggers_correctly

## Bug 2: Text mode for binary operation (line 33)
- `compress_file()` opens source in text mode ('r') but gzip.open expects bytes ('wb')
- Writing a string to a bytes file raises TypeError
- **Breaks**: test_compression_works_correctly

## Bug 3: Missing directory in rotated path (line 48)
- Rotated filename uses only basename, losing the directory path
- File gets created in current working directory instead of the log directory
- **Breaks**: test_rotated_filename_preserves_extension, test_full_rotation_workflow

## Bug 4: Uncompressed file not removed after compression (line 60)
- After gzip compression, the original uncompressed rotated file is left behind
- Should call os.remove(rotated_name) after successful compression
- **Breaks**: test_compressed_files_handled_in_rotation

## Bug 5: Incorrect rotated file detection (line 77)
- cleanup_old_logs doesn't account for .gz extension in rotated files
- **Breaks**: test_multiple_rotations_with_max_backups

## Bug 6: Wrong sort order for cleanup (line 81)
- Sorts alphabetically instead of by modification time
- Deletes wrong files when enforcing retention policy
- **Breaks**: test_multiple_rotations_with_max_backups
