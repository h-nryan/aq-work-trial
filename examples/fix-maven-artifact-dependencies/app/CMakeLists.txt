cmake_minimum_required(VERSION 3.16)

add_executable(calculator src/main.cpp)

# Intentionally wrong order: calc before math
# Also missing explicit add_dependencies(calculator math calc)
# Missing RPATH setup intentionally - will fail at runtime
# Intentionally missing include dirs propagation from libs forces manual includes (broken design)
target_link_libraries(calculator PRIVATE calc math)
