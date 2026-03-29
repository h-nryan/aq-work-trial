#!/bin/bash
set -euo pipefail

# Enable compile_commands.json at top-level if missing
if ! grep -q "CMAKE_EXPORT_COMPILE_COMMANDS" /app/CMakeLists.txt; then
  if grep -qE '^\s*project\(' /app/CMakeLists.txt; then
    perl -0777 -pe 'BEGIN{$/=undef} s/(project\([^)]+\)\s*)/$1\nset(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n/;' -i /app/CMakeLists.txt
  else
    printf "\nset(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n" >> /app/CMakeLists.txt
  fi
fi

# Ensure bin/lib output dirs at top-level
if ! grep -q "CMAKE_RUNTIME_OUTPUT_DIRECTORY" /app/CMakeLists.txt; then
  printf "\nset(CMAKE_RUNTIME_OUTPUT_DIRECTORY \${CMAKE_BINARY_DIR}/bin)\nset(CMAKE_LIBRARY_OUTPUT_DIRECTORY \${CMAKE_BINARY_DIR}/lib)\nset(CMAKE_ARCHIVE_OUTPUT_DIRECTORY \${CMAKE_BINARY_DIR}/lib)\n" >> /app/CMakeLists.txt
fi

# Fix libmath: PUBLIC includes, SONAME, install rules
perl -0777 -pe 'BEGIN{$/=undef;}
 s/target_include_directories\(\s*math\s+PRIVATE\s+include\s*\)/target_include_directories(math PUBLIC include)/g;
 if(!/set_target_properties\(\s*math/){ 
   s/add_library\(\s*math[^\)]*\)\s*/$&\n\nset_target_properties(math PROPERTIES VERSION 1.0.0 SOVERSION 1)\n/; 
 }
 if(!/install\(\s*TARGETS\s+math/){ 
   s/$/.push("\ninstall(TARGETS math LIBRARY DESTINATION lib)")/e; 
 }
' -i /app/libs/libmath/CMakeLists.txt

# Fix libcalc: PUBLIC includes, link to math, SONAME, install rules  
perl -0777 -pe 'BEGIN{$/=undef;}
 s/target_include_directories\(\s*calc\s+PRIVATE\s+include\s*\)/target_include_directories(calc PUBLIC include)/g;
 if(!/target_link_libraries\(\s*calc\b/){ 
   s/add_library\(\s*calc[^\)]*\)\s*/$&\n\ntarget_link_libraries(calc PUBLIC math)\n/; 
 }
 if(!/set_target_properties\(\s*calc/){ 
   s/add_library\(\s*calc[^\)]*\)\s*/$&\n\nset_target_properties(calc PROPERTIES VERSION 1.0.0 SOVERSION 1)\n/; 
 }
 if(!/install\(\s*TARGETS\s+calc/){ 
   s/$/.push("\ninstall(TARGETS calc LIBRARY DESTINATION lib)")/e; 
 }
' -i /app/libs/libcalc/CMakeLists.txt

# Fix calculator app: correct link order, explicit dependencies, RPATH
perl -0777 -pe 'BEGIN{$/=undef;}
 s/target_link_libraries\(\s*calculator\s+PRIVATE\s+calc\s+math\s*\)/target_link_libraries(calculator PRIVATE math calc)/g;
 if(!/add_dependencies\(\s*calculator\s+math\s+calc\s*\)/){ 
   s/add_executable\([^\)]*\)/$&\n\nadd_dependencies(calculator math calc)\n/; 
 }
 if(!/set_target_properties\(\s*calculator/){ 
   s/target_link_libraries\([^\)]*\)/$&\n\nset_target_properties(calculator PROPERTIES BUILD_RPATH "\${CMAKE_BINARY_DIR}\/lib")\n/; 
 }
 s/^.*target_include_directories\(\s*calculator\b.*\n?//mg;
' -i /app/app/CMakeLists.txt

echo "CMake fixes applied. Now run: mkdir -p build && cd build && cmake .. && cmake --build . -j"
