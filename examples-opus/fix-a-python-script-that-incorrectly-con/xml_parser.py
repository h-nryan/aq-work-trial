#!/usr/bin/env python3
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path

def parse_xml_to_dict(element):
    """Recursively parse XML element to dictionary"""
    result = {}
    
    # Add attributes
    if element.attrib:
        result['@attributes'] = element.attrib
    
    # Add text content
    # BUG 1: Missing strip() - includes whitespace in text content
    if element.text and element.text.strip():
        result['@text'] = element.text
    
    # Process children
    children = list(element)
    if children:
        child_dict = {}
        for child in children:
            child_data = parse_xml_to_dict(child)
            
            # BUG 2: Doesn't handle multiple children with same tag name
            # Should create a list when duplicate tags exist
            child_dict[child.tag] = child_data
        
        result.update(child_dict)
    
    return result

def parse_xml_file(filepath, pretty=False):
    """Parse XML file and return JSON string"""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        
        # BUG 3: Missing root element wrapper - loses root tag name
        data = parse_xml_to_dict(root)
        
        if pretty:
            return json.dumps(data, indent=2, ensure_ascii=False)
        else:
            # BUG 4: Missing separators parameter for compact output
            return json.dumps(data, ensure_ascii=False)
    
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

def main():
    args = sys.argv[1:]
    
    if len(args) < 1:
        print("Usage: python xml_parser.py [--pretty] <input.xml>", file=sys.stderr)
        sys.exit(2)
    
    pretty = False
    filepath = None
    
    # Simple argument parsing
    for arg in args:
        if arg == "--pretty":
            pretty = True
        elif not arg.startswith("-"):
            filepath = arg
    
    if not filepath:
        print("Usage: python xml_parser.py [--pretty] <input.xml>", file=sys.stderr)
        sys.exit(2)
    
    result = parse_xml_file(filepath, pretty)
    print(result)

if __name__ == "__main__":
    main()
