#!/bin/bash
set -euo pipefail

# Fix all bugs in the config parser
cat > /app/config_parser.py << 'EOF'
#!/usr/bin/env python3
import os
import sys
from typing import Any, Dict


class ConfigParser:
    """Parse configuration files with type coercion and default values."""
    
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.config: Dict[str, Any] = {}
        self.defaults: Dict[str, Any] = {
            'host': 'localhost',
            'port': 8080,
            'debug': False,
            'timeout': 30,
            'max_connections': 100
        }
    
    def parse(self) -> Dict[str, Any]:
        """Parse config file and return configuration dictionary."""
        # Start with defaults
        result = self.defaults.copy()
        
        if not os.path.exists(self.config_file):
            self.config = result
            return result
        
        with open(self.config_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if '=' not in line:
                    continue
                
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Type coercion based on default type
                if key in self.defaults:
                    default_type = type(self.defaults[key])
                    if default_type == bool:
                        result[key] = value.lower() in ('true', '1', 'yes')
                    elif default_type == int:
                        try:
                            result[key] = int(value)
                        except ValueError:
                            result[key] = value
                    else:
                        result[key] = value
                else:
                    # No default, try to infer type
                    if value.lower() in ('true', 'false'):
                        result[key] = value.lower() == 'true'
                    elif value.isdigit():
                        result[key] = int(value)
                    else:
                        result[key] = value
        
        self.config = result
        return result
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with optional default."""
        if key in self.config:
            return self.config[key]
        if default is not None:
            return default
        if key in self.defaults:
            return self.defaults[key]
        return None
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get configuration value as integer."""
        value = self.get(key, default)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get configuration value as boolean."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes')
        return default


def main():
    if len(sys.argv) < 2:
        print("Usage: config_parser.py <config_file>")
        sys.exit(1)
    
    parser = ConfigParser(sys.argv[1])
    config = parser.parse()
    
    print("Configuration:")
    print(f"  host: {parser.get('host', 'localhost')}")
    print(f"  port: {parser.get_int('port', 8080)}")
    print(f"  debug: {parser.get_bool('debug', False)}")
    print(f"  timeout: {parser.get_int('timeout', 30)}")
    print(f"  max_connections: {parser.get_int('max_connections', 100)}")


if __name__ == '__main__':
    main()
EOF

chmod +x /app/config_parser.py
