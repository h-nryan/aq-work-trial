#!/usr/bin/env python3
import sys
import json
import xml.etree.ElementTree as ET
from collections import OrderedDict

def strip_namespace(tag):
    """Remove namespace from tag name."""
    # BUG 2: Namespace stripping doesn't work correctly
    # Should handle {namespace}tag format, but only checks for ':'
    if ':' in tag:
        return tag.split(':', 1)[1]
    return tag

def parse_element(element, strip_ns=False):
    """Parse an XML element into a dictionary structure."""
    result = OrderedDict()
    
    # BUG 1: Attributes are stored with wrong prefix
    # Should use '@' prefix for attributes, but uses 'attr_' instead
    if element.attrib:
        for key, value in element.attrib.items():
            attr_key = strip_namespace(key) if strip_ns else key
            result[f"attr_{attr_key}"] = value
    
    # BUG 4: Text content handling is broken
    # Should check element.text, but checks element.tail instead
    if element.tail and element.tail.strip():
        result['#text'] = element.tail.strip()
    
    # Handle child elements
    children = list(element)
    if children:
        for child in children:
            child_data = parse_element(child, strip_ns)
            
            # Strip namespace from tag if requested
            tag = strip_namespace(child.tag) if strip_ns else child.tag
            
            if tag in result:
                # Multiple children with same tag - convert to list
                if not isinstance(result[tag], list):
                    result[tag] = [result[tag]]
                result[tag].append(child_data)
            else:
                result[tag] = child_data
    
    return result

def xml_to_json(xml_file, pretty=False, strip_ns=False):
    """Convert XML file to JSON format."""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # BUG 3: strip_ns flag is not actually used when parsing
        # Should pass strip_ns to parse_element, but doesn't
        root_tag = strip_namespace(root.tag) if strip_ns else root.tag
        result = {root_tag: parse_element(root)}
        
        # Format output
        if pretty:
            return json.dumps(result, indent=2, ensure_ascii=False)
        else:
            return json.dumps(result, ensure_ascii=False)
    
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: File '{xml_file}' not found", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: xml_to_json.py <xml_file> [--pretty] [--strip-namespace]")
        sys.exit(1)
    
    xml_file = sys.argv[1]
    pretty = '--pretty' in sys.argv
    strip_ns = '--strip-namespace' in sys.argv
    
    json_output = xml_to_json(xml_file, pretty=pretty, strip_ns=strip_ns)
    print(json_output)

if __name__ == '__main__':
    main()
