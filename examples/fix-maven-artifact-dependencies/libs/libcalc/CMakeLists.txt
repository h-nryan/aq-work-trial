cmake_minimum_required(VERSION 3.16)

add_library(calc SHARED
    src/calc.cpp
)

# Intentionally broken: PRIVATE include dirs (should be PUBLIC)
target_include_directories(calc PRIVATE include)

# Intentionally missing: link to math is not declared as dependency
# (app will try to link calc then math, causing order issue)
# Intentionally missing: no SONAME/versioning
# Intentionally missing: no install rules
