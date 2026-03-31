#!/bin/bash

# Solution: Fix all bugs in template_engine.py
cat > /app/template_engine.py << 'EOF'
#!/usr/bin/env python3
import re
import html
import sys

class TemplateEngine:
    def __init__(self):
        self.variables = {}
    
    def set_variable(self, name, value):
        """Set a template variable"""
        self.variables[name] = value
    
    def render(self, template_string):
        """Render a template with variable substitution and escaping"""
        result = template_string
        
        # FIX BUG 1: Correct regex pattern to handle whitespace around variable names
        pattern = r'\{\{\s*(\w+)\s*\}\}'
        
        def replace_var(match):
            var_name = match.group(1)
            
            if var_name in self.variables:
                value = str(self.variables[var_name])
                # FIX BUG 2: Use html.escape() instead of html.unescape()
                return html.escape(value)
            else:
                # FIX BUG 3: Return the original placeholder instead of empty string
                return match.group(0)
        
        result = re.sub(pattern, replace_var, result)
        return result
    
    def render_file(self, filepath):
        """Render a template file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            template = f.read()
        return self.render(template)
    
    def render_with_context(self, template_string, context):
        """Render template with a context dictionary"""
        # FIX BUG 4: Merge context with existing variables instead of replacing
        old_vars = self.variables.copy()
        self.variables.update(context)
        result = self.render(template_string)
        self.variables = old_vars
        return result
    
    def escape_html(self, text):
        """Manually escape HTML special characters"""
        replacements = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;'
        }
        
        result = text
        for char, escaped in replacements.items():
            result = result.replace(char, escaped)
        return result

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python template_engine.py <template_file>")
        sys.exit(1)
    
    engine = TemplateEngine()
    engine.set_variable('title', 'Welcome')
    engine.set_variable('name', 'User')
    
    output = engine.render_file(sys.argv[1])
    print(output)
EOF

chmod +x /app/template_engine.py
