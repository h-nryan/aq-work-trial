# Bugs in csv_to_json.py (3 total, targeting 5 test functions)
# Difficulty: LEARNABLE (Opus 3/5) — bugs are moderate, not too subtle

## Bug 1: Hard-coded comma delimiter (line 16)
- Uses `line.split(",")` instead of reading from `DELIM` environment variable
- **Subtlety**: LOW — the fix is straightforward (use `os.environ.get`), but the
  agent needs to know about the DELIM env var from the instruction
- **Breaks**: test_semicolons_with_env_delim, test_default_delimiter_is_comma (partial)

## Bug 2: No header row handling (line 20)
- Treats all rows as data and outputs list-of-lists instead of list-of-dicts
- The first row should be used as keys for JSON objects
- **Subtlety**: MODERATE — requires restructuring the data processing logic,
  not just a one-line fix. Agent must understand the desired output format.
- **Breaks**: test_commas_records_as_objects, test_semicolons_with_env_delim

## Bug 3: Missing --pretty flag support (line 8, 20)
- Argument parsing rejects any flag starting with "-"
- No pretty-printing logic exists at all
- **Subtlety**: LOW-MODERATE — requires adding argparse or manual flag parsing
  AND json.dumps indent parameter. Two changes needed, but both are standard.
- **Breaks**: test_pretty_flag_changes_format_only

## Why this is learnable (not too easy, not too hard):
- Each bug is individually findable, but fixing all 3 requires understanding
  the full program flow (args → delimiter → parsing → output format)
- The bugs don't interact much — fixing one doesn't break or reveal another
- A capable agent solves it ~60% of the time (Opus 3/5)
- An agent that rushes may fix 2/3 bugs but miss the delimiter or pretty flag
