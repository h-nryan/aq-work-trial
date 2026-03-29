cmake_minimum_required(VERSION 3.16)

project(SharedLibRpathFix LANGUAGES CXX)

# Intentionally missing CMAKE_EXPORT_COMPILE_COMMANDS
# Output directories
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

add_subdirectory(libs/libmath)
add_subdirectory(libs/libcalc)
add_subdirectory(app)
