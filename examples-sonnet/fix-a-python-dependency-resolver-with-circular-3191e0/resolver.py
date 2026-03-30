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
        
        # BUG 1: Version selection ignores the version_constraint parameter
        # Always picks first available version instead of checking if constraint matches
        available_versions = list(self.packages[name].keys())
        if not available_versions:
            raise ValueError(f"No versions available for {name}")
        version = available_versions[0]
        
        pkg_key = (name, version)
        
        # BUG 2: Missing circular dependency detection
        # Should check if pkg_key is in self.visiting BEFORE adding to it
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
        
        # BUG 3: Missing cleanup - should remove pkg_key from self.visiting
        # Without this, the visiting set grows unbounded and circular dep detection would fail even if Bug 2 was fixed
        self.visited.add(pkg_key)
        
        return result


def main():
    if len(sys.argv) < 2:
        print("Usage: resolver.py <command> [args]")
        sys.exit(1)
    
    command = sys.argv[1]
    resolver = DependencyResolver()
    
    if command == "resolve":
        # BUG 4: Wrong argument count check - should be < 4, not < 3
        # This causes IndexError when accessing sys.argv[3] with only 3 args total
        if len(sys.argv) < 3:
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
