import json
import subprocess
from pathlib import Path

def read_json(p):
    """Read and parse JSON from file path."""
    txt = Path(p).read_text(encoding="utf-8")
    return json.loads(txt)

def run_parser(xml_file, pretty=False):
    """Run the XML parser and return parsed JSON output."""
    cmd = ['python3', 'xml_parser.py']
    if pretty:
        cmd.append('--pretty')
    cmd.append(xml_file)
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd='/app'
    )
    
    if result.returncode != 0:
        raise Exception(f"Parser failed: {result.stderr}")
    
    return json.loads(result.stdout)

def test_simple_xml_structure():
    """Test that simple XML is converted to correct JSON structure."""
    data = read_json("/tmp/out_simple.json")
    
    # Should have root element
    assert 'root' in data, "Root element 'root' should be preserved"
    root = data['root']
    
    # Check basic fields
    assert 'name' in root, "Should have 'name' field"
    assert 'age' in root, "Should have 'age' field"
    assert 'city' in root, "Should have 'city' field"
    
    # Check values with proper text extraction
    assert root['name']['@text'] == 'Alice', f"Expected 'Alice', got {root['name']}"
    assert root['age']['@text'] == '30', f"Expected '30', got {root['age']}"
    assert root['city']['@text'] == 'New York', f"Expected 'New York', got {root['city']}"

def test_text_content_stripped():
    """Test that text content has whitespace properly stripped."""
    data = read_json("/tmp/out_simple.json")
    root = data['root']
    
    # Text should not contain newlines or extra spaces
    name_text = root['name']['@text']
    assert '\n' not in name_text, "Text should not contain newlines"
    assert name_text == name_text.strip(), "Text should be stripped"

def test_nested_xml_structure():
    """Test that nested XML structures are preserved correctly."""
    data = read_json("/tmp/out_nested.json")
    
    assert 'company' in data, "Root element 'company' should be preserved"
    company = data['company']
    
    assert 'name' in company, "Company should have name"
    assert 'employees' in company, "Company should have employees"
    
    employees = company['employees']
    assert 'employee' in employees, "Employees should contain employee elements"

def test_duplicate_elements_become_array():
    """Test that duplicate XML elements are converted to JSON array."""
    data = read_json("/tmp/out_duplicates.json")
    
    assert 'catalog' in data, "Root element 'catalog' should be preserved"
    catalog = data['catalog']
    
    assert 'item' in catalog, "Catalog should have 'item' field"
    items = catalog['item']
    
    # Multiple items should be in an array
    assert isinstance(items, list), f"Duplicate elements should be array, got {type(items)}"
    assert len(items) == 3, f"Should have 3 items, got {len(items)}"
    
    # Check item values
    item_texts = [item['@text'] for item in items]
    assert 'Book' in item_texts, "Should contain 'Book'"
    assert 'Pen' in item_texts, "Should contain 'Pen'"
    assert 'Notebook' in item_texts, "Should contain 'Notebook'"

def test_attributes_preserved():
    """Test that XML attributes are preserved in @attributes field."""
    data = read_json("/tmp/out_attributes.json")
    
    assert 'book' in data, "Root element 'book' should be preserved"
    book = data['book']
    
    # Check root attributes
    assert '@attributes' in book, "Book should have @attributes field"
    attrs = book['@attributes']
    assert 'isbn' in attrs, "Should preserve isbn attribute"
    assert 'lang' in attrs, "Should preserve lang attribute"
    assert attrs['isbn'] == '978-0-123456-78-9', "ISBN should match"
    assert attrs['lang'] == 'en', "Language should match"
    
    # Check nested element with attributes
    assert 'author' in book, "Book should have author"
    author = book['author']
    assert '@attributes' in author, "Author should have @attributes"
    assert author['@attributes']['nationality'] == 'US', "Nationality should match"
    assert '@text' in author, "Author should have text content"
    assert author['@text'] == 'John Doe', "Author name should match"

def test_compact_json_format():
    """Test that compact JSON has no unnecessary whitespace."""
    output = Path("/tmp/out_simple.json").read_text()
    
    # Compact JSON should not have spaces after colons or commas
    # (when using separators=(',', ':'))
    assert ', ' not in output or ': ' not in output, "Compact JSON should use minimal spacing"
    
    # Should be valid JSON
    data = json.loads(output)
    assert data is not None, "Should be valid JSON"

def test_pretty_json_format():
    """Test that --pretty flag produces indented output."""
    output = Path("/tmp/out_pretty.json").read_text()
    
    # Pretty JSON should have newlines and indentation
    assert '\n' in output, "Pretty JSON should have newlines"
    assert '  ' in output, "Pretty JSON should have indentation"
    
    # Should parse to same structure as compact
    pretty_data = json.loads(output)
    compact_data = read_json("/tmp/out_simple.json")
    
    assert pretty_data == compact_data, "Pretty and compact should have same data"

def test_multiple_nested_duplicates():
    """Test handling of multiple employee elements in nested structure."""
    data = read_json("/tmp/out_nested.json")
    
    employees = data['company']['employees']
    employee_list = employees['employee']
    
    # Should be an array of employees
    assert isinstance(employee_list, list), "Multiple employees should be in array"
    assert len(employee_list) == 2, f"Should have 2 employees, got {len(employee_list)}"
    
    # Check first employee
    emp1 = employee_list[0]
    assert '@attributes' in emp1, "Employee should have attributes"
    assert emp1['@attributes']['id'] == '1', "First employee ID should be 1"
    assert emp1['name']['@text'] == 'Bob', "First employee name should be Bob"
    assert emp1['role']['@text'] == 'Engineer', "First employee role should be Engineer"
    
    # Check second employee
    emp2 = employee_list[1]
    assert emp2['@attributes']['id'] == '2', "Second employee ID should be 2"
    assert emp2['name']['@text'] == 'Carol', "Second employee name should be Carol"
    assert emp2['role']['@text'] == 'Manager', "Second employee role should be Manager"

def test_root_element_always_preserved():
    """Test that root element tag is always preserved in output."""
    # Test all sample files
    samples = [
        ('sample_data/simple.xml', 'root'),
        ('sample_data/nested.xml', 'company'),
        ('sample_data/attributes.xml', 'book'),
        ('sample_data/duplicates.xml', 'catalog')
    ]
    
    for xml_file, expected_root in samples:
        data = run_parser(xml_file)
        assert expected_root in data, f"Root element '{expected_root}' should be preserved in {xml_file}"
        assert len(data) == 1, f"Output should have exactly one root key for {xml_file}"
