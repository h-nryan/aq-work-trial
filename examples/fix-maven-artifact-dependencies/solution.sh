#!/bin/bash

set -euo pipefail

# Fix top-level CMake to export compile commands for tests
if ! grep -q "^set(CMAKE_EXPORT_COMPILE_COMMANDS ON)" CMakeLists.txt; then
  if grep -qE '^\s*project\(' CMakeLists.txt; then
    perl -0777 -pe 'BEGIN{$/=undef} s/(project\([^\)]*\)\s*)/$1\n\nset(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n/;' -i CMakeLists.txt
  else
    printf "\nset(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n" >> CMakeLists.txt
  fi
fi

# Fix libmath: export PUBLIC include dirs, add SONAME and versioning, add install rules
perl -0777 -pe 'BEGIN{$/=undef;}
 s/target_include_directories\(\s*math\s+PRIVATE\s+include\s*\)/target_include_directories(math PUBLIC include)/g;
 # Add SONAME and versioning
 if(!/set_target_properties\(\s*math/){ 
   s/add_library\(\s*math[^\)]*\)\s*/$&\n\nset_target_properties(math PROPERTIES\n  VERSION 1.0.0\n  SOVERSION 1\n)\n/; 
 }
 # Add install rules
 if(!/install\(\s*TARGETS\s+math/){ 
   s/target_include_directories\([^\)]*\)/$&\n\ninstall(TARGETS math\n  LIBRARY DESTINATION lib\n  ARCHIVE DESTINATION lib\n  RUNTIME DESTINATION bin\n)\n/; 
 }
' -i libs/libmath/CMakeLists.txt

# Fix libcalc: export PUBLIC include dirs, link to math, add SONAME and versioning, add install rules
perl -0777 -pe 'BEGIN{$/=undef;}
 s/target_include_directories\(\s*calc\s+PRIVATE\s+include\s*\)/target_include_directories(calc PUBLIC include)/g;
 # Ensure calc links to math to establish dependency
 if(!/target_link_libraries\(\s*calc\b/){ 
   s/add_library\(\s*calc[^\)]*\)\s*/$&\n\ntarget_link_libraries(calc PUBLIC math)\n/; 
 }
 # Add SONAME and versioning
 if(!/set_target_properties\(\s*calc/){ 
   s/add_library\(\s*calc[^\)]*\)\s*/$&\n\nset_target_properties(calc PROPERTIES\n  VERSION 1.0.0\n  SOVERSION 1\n)\n/; 
 }
 # Add install rules
 if(!/install\(\s*TARGETS\s+calc/){ 
   s/target_include_directories\([^\)]*\)/$&\n\ninstall(TARGETS calc\n  LIBRARY DESTINATION lib\n  ARCHIVE DESTINATION lib\n  RUNTIME DESTINATION bin\n)\n/; 
 }
' -i libs/libcalc/CMakeLists.txt

# Fix calculator app: correct link order, explicit dependencies, RPATH
perl -0777 -pe 'BEGIN{$/=undef;}
 s/target_link_libraries\(\s*calculator\s+PRIVATE\s+calc\s+math\s*\)/target_link_libraries(calculator PRIVATE math calc)/g;
 if(!/add_dependencies\(\s*calculator\s+math\s+calc\s*\)/){ 
   s/add_executable\([^\)]*\)/$&\n\nadd_dependencies(calculator math calc)\n/; 
 }
 # Configure RPATH so executable can find shared libraries
 if(!/set_target_properties\(\s*calculator/){ 
   s/target_link_libraries\([^\)]*\)/$&\n\nset_target_properties(calculator PROPERTIES\n  INSTALL_RPATH "\$ORIGIN\/..\/lib"\n  BUILD_RPATH "\${CMAKE_BINARY_DIR}\/lib"\n)\n/; 
 }
 s/^.*target_include_directories\(\s*calculator\b.*\n?//mg;
' -i app/CMakeLists.txt

# Do not build here; tests will install toolchain and perform the build
