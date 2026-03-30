import subprocess
import json
import pytest

def run_converter(xml_file, *args):
    """Run the XML to JSON converter and return output."""
    cmd = ['python3', '/app/xml_to_json.py', xml_file] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def test_simple_attributes_mapping():
    """Test that XML attributes are mapped with @ prefix."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/simple.xml')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    data = json.loads(stdout)
    
    book = data['book']
    assert '@id' in book, "Attributes should use @ prefix, not attr_ prefix"
    assert '@category' in book, "Attributes should use @ prefix"
    assert book['@id'] == '123', "Attribute value should be preserved"
    assert book['@category'] == 'fiction', "Attribute value should be preserved"

def test_namespace_stripping():
    """Test that --strip-namespace flag removes namespace prefixes."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/namespaced.xml', '--strip-namespace')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    data = json.loads(stdout)
    
    # Should have 'catalog' not 'ns:catalog' or '{http://example.com/catalog}catalog'
    assert 'catalog' in data, "Root tag should be stripped of namespace"
    assert 'ns:catalog' not in data, "Namespace prefix should be removed"
    
    catalog = data['catalog']
    assert 'product' in catalog, "Child tags should be stripped of namespace"
    assert 'ns:product' not in catalog, "Namespace prefix should be removed"

def test_namespace_in_attributes():
    """Test that namespaced attributes are handled correctly."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/namespaced.xml', '--strip-namespace')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    data = json.loads(stdout)
    
    product = data['catalog']['product']
    assert '@id' in product, "Namespaced attributes should use @ prefix"
    assert product['@id'] == 'P001', "Attribute value should be preserved"

def test_multiple_children_same_tag():
    """Test that multiple children with same tag become an array."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/multiple.xml')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    data = json.loads(stdout)
    
    library = data['library']
    assert 'book' in library, "Should have book elements"
    assert isinstance(library['book'], list), "Multiple children with same tag should be a list"
    assert len(library['book']) == 3, "Should have 3 book elements"
    
    # Check that attributes are correctly mapped in array items
    for i, book in enumerate(library['book'], 1):
        assert '@id' in book, f"Book {i} should have @id attribute"
        assert book['@id'] == str(i), f"Book {i} should have correct id"

def test_text_content_preserved():
    """Test that text content is preserved in #text keys."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/simple.xml')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    data = json.loads(stdout)
    
    book = data['book']
    assert 'title' in book, "Should have title element"
    assert '#text' in book['title'], "Text content should be in #text key"
    assert book['title']['#text'] == 'The Great Adventure', "Text content should be preserved"

def test_pretty_print_format():
    """Test that --pretty flag produces indented JSON."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/simple.xml', '--pretty')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    
    # Pretty printed JSON should have newlines and indentation
    assert '\n' in stdout, "Pretty print should have newlines"
    assert '  ' in stdout, "Pretty print should have indentation"
    
    # Should still be valid JSON
    data = json.loads(stdout)
    assert 'book' in data, "Should still parse as valid JSON"

def test_complex_namespace_handling():
    """Test complex XML with nested namespaces and attributes."""
    stdout, stderr, returncode = run_converter('/tmp/xml_test/complex.xml', '--strip-namespace')
    
    assert returncode == 0, f"Converter failed: {stderr}"
    data = json.loads(stdout)
    
    assert 'root' in data, "Root should be stripped of namespace"
    root = data['root']
    assert 'metadata' in root, "Nested elements should be stripped of namespace"
    
    metadata = root['metadata']
    assert '@version' in metadata, "Attributes should use @ prefix"
    assert '@type' in metadata, "Namespaced attributes should be stripped and use @ prefix"
    
    # Check that multiple settings are in an array
    assert 'setting' in metadata, "Should have setting elements"
    assert isinstance(metadata['setting'], list), "Multiple settings should be a list"
    assert len(metadata['setting']) == 2, "Should have 2 setting elements"
