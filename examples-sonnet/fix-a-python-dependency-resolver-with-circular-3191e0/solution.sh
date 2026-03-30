#!/bin/bash
set -euo pipefail

cat > /app/resolver.py << 'EOF'
#!/usr/bin/env python3
import sys
import json
from typing import Dict, List, Set, Tuple, Optional


class Package:
    def __init__(self, name: str, version: str, dependencies: Dict[str, str]):
        self.name = name
        self.version = version
        self.dependencies = dependencies


class DependencyResolver:
    def __init__(self):
        self.packages: Dict[str, Dict[str, Package]] = {}
        self.visited: Set[Tuple[str, str]] = set()
        self.visiting: Set[Tuple[str, str]] = set()

    def add_package(self, name: str, version: str, dependencies: Dict[str, str]):
        if name not in self.packages:
            self.packages[name] = {}
        self.packages[name][version] = Package(name, version, dependencies)

    def resolve(self, requirements: Dict[str, str]) -> List[Tuple[str, str]]:
        self.visited.clear()
        self.visiting.clear()
        result = []
        
        for pkg_name, version_constraint in requirements.items():
            resolved = self._resolve_package(pkg_name, version_constraint)
            for pkg, ver in resolved:
                if (pkg, ver) not in result:
                    result.append((pkg, ver))
        
        return result

    def _resolve_package(self, name: str, version_constraint: str) -> List[Tuple[str, str]]:
        if name not in self.packages:
            raise ValueError(f"Package {name} not found")
        
        # FIX: Properly select version based on constraint
        if version_constraint in self.packages[name]:
            version = version_constraint
        else:
            available_versions = list(self.packages[name].keys())
            if not available_versions:
                raise ValueError(f"No versions available for {name}")
            version = available_versions[0]
        
        pkg_key = (name, version)
        
        # FIX: Check for circular dependencies before processing
        if pkg_key in self.visiting:
            raise ValueError(f"Circular dependency detected: {name}@{version}")
        
        if pkg_key in self.visited:
            return []
        
        self.visiting.add(pkg_key)
        
        package = self.packages[name][version]
        result = [(name, version)]
        
        for dep_name, dep_version in package.dependencies.items():
            dep_resolved = self._resolve_package(dep_name, dep_version)
            for dep_pkg, dep_ver in dep_resolved:
                if (dep_pkg, dep_ver) not in result:
                    result.append((dep_pkg, dep_ver))
        
        # FIX: Remove from visiting set after processing
        self.visiting.remove(pkg_key)
        self.visited.add(pkg_key)
        
        return result


def main():
    if len(sys.argv) < 2:
        print("Usage: resolver.py <command> [args]")
        sys.exit(1)
    
    command = sys.argv[1]
    resolver = DependencyResolver()
    
    if command == "resolve":
        if len(sys.argv) < 4:
            print("Usage: resolver.py resolve <registry.json> <requirements.json>")
            sys.exit(1)
        
        registry_file = sys.argv[2]
        requirements_file = sys.argv[3]
        
        with open(registry_file) as f:
            registry = json.load(f)
        
        for pkg_name, versions in registry.items():
            for version, deps in versions.items():
                resolver.add_package(pkg_name, version, deps)
        
        with open(requirements_file) as f:
            requirements = json.load(f)
        
        try:
            resolved = resolver.resolve(requirements)
            output = {pkg: ver for pkg, ver in resolved}
            print(json.dumps(output, indent=2))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
EOF

chmod +x /app/resolver.py
