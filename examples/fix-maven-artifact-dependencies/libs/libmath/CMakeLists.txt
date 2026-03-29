cmake_minimum_required(VERSION 3.16)

add_library(math SHARED
    src/math.cpp
)

# Intentionally broken: PRIVATE include dirs (should be PUBLIC)
target_include_directories(math PRIVATE include)

# Intentionally missing: no SONAME/versioning
# Intentionally missing: no install rules
