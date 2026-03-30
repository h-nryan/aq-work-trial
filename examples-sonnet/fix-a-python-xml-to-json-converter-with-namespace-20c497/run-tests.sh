#!/bin/bash

# Install curl

# Install uv


# Check if we're in a valid working directory
if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

uv init
uv add pytest==8.4.1

# Create sample XML files for testing
mkdir -p /tmp/xml_test

# Sample 1: Simple XML with attributes
cat > /tmp/xml_test/simple.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<book id="123" category="fiction">
    <title>The Great Adventure</title>
    <author>John Doe</author>
    <year>2023</year>
</book>
EOF

# Sample 2: XML with namespaces
cat > /tmp/xml_test/namespaced.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<ns:catalog xmlns:ns="http://example.com/catalog">
    <ns:product ns:id="P001">
        <ns:name>Widget</ns:name>
        <ns:price>19.99</ns:price>
    </ns:product>
</ns:catalog>
EOF

# Sample 3: XML with multiple children of same tag
cat > /tmp/xml_test/multiple.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<library>
    <book id="1">
        <title>Book One</title>
    </book>
    <book id="2">
        <title>Book Two</title>
    </book>
    <book id="3">
        <title>Book Three</title>
    </book>
</library>
EOF

# Sample 4: Complex nested XML with attributes and namespaces
cat > /tmp/xml_test/complex.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<root xmlns:app="http://example.com/app">
    <app:metadata version="1.0" app:type="config">
        <app:setting name="timeout">30</app:setting>
        <app:setting name="retries">3</app:setting>
    </app:metadata>
</root>
EOF

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
