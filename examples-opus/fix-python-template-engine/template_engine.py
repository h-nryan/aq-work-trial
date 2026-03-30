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
        
        # BUG 1: Wrong regex pattern - doesn't handle whitespace around variable names
        # Should be r'\{\{\s*(\w+)\s*\}\}' to match optional whitespace
        pattern = r'\{\{(\w+)\}\}'
        
        def replace_var(match):
            var_name = match.group(1)
            # Variable name is captured without whitespace handling
            
            if var_name in self.variables:
                value = str(self.variables[var_name])
                # BUG 2: Using wrong escaping function - unescape instead of escape
                # Should use html.escape() but uses html.unescape() instead
                return html.unescape(value)
            else:
                # BUG 3: Returns empty string instead of keeping placeholder
                # Should return match.group(0) to preserve undefined variables
                return ""
        
        result = re.sub(pattern, replace_var, result)
        return result
    
    def render_file(self, filepath):
        """Render a template file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            template = f.read()
        return self.render(template)
    
    def render_with_context(self, template_string, context):
        """Render template with a context dictionary"""
        # BUG 4: Doesn't properly merge context with existing variables
        # Should preserve existing variables and update with context
        self.variables = context
        return self.render(template_string)
    
    def escape_html(self, text):
        """Manually escape HTML special characters"""
        # Missing single quote escaping
        replacements = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;'
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
