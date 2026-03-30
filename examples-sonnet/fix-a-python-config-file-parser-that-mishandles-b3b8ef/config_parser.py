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
        if not os.path.exists(self.config_file):
            return self.defaults.copy()
        
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
                
                # BUG 1: Type coercion doesn't handle integers correctly
                # Stores integers as strings instead of converting to int
                if value.lower() == 'true':
                    self.config[key] = True
                elif value.lower() == 'false':
                    self.config[key] = False
                elif value.isdigit():
                    self.config[key] = value  # BUG: stores as string, not int
                else:
                    self.config[key] = value
        
        # BUG 2: Doesn't merge with defaults - only returns parsed values
        # Missing keys from defaults won't be included
        return self.config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with optional default."""
        # BUG 3: Ignores the default parameter passed to get()
        # Always returns None if key not found, instead of using default
        if key in self.config:
            return self.config[key]
        return None
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get configuration value as integer."""
        value = self.get(key, default)
        if isinstance(value, int):
            return value
        # BUG 4: Doesn't handle string-to-int conversion properly
        # Returns default even when value exists but is string
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
