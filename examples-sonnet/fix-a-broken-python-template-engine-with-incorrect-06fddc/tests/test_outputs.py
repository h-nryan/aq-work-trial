import sys
import os
sys.path.insert(0, '/app')

from template_engine import TemplateEngine
import html


def test_basic_variable_substitution():
    """Test that basic variable substitution works correctly"""
    engine = TemplateEngine()
    engine.set_variable('name', 'Alice')
    engine.set_variable('age', '25')
    
    template = 'Hello {{ name }}, you are {{ age }} years old.'
    result = engine.render(template)
    
    assert 'Alice' in result, "Variable 'name' should be substituted"
    assert '25' in result, "Variable 'age' should be substituted"
    assert '{{' not in result, "No placeholders should remain for defined variables"


def test_whitespace_handling():
    """Test that whitespace around variable names is handled correctly"""
    engine = TemplateEngine()
    engine.set_variable('var1', 'value1')
    engine.set_variable('var2', 'value2')
    
    # Test various whitespace patterns
    template = '{{var1}} {{ var1 }} {{  var1  }} {{ var2}}'
    result = engine.render(template)
    
    # All variations should be replaced
    assert result.count('value1') == 3, "All whitespace variations of var1 should be replaced"
    assert result.count('value2') == 1, "var2 should be replaced"
    assert '{{' not in result, "No placeholders should remain"


def test_html_escaping():
    """Test that HTML special characters are properly escaped"""
    engine = TemplateEngine()
    engine.set_variable('content', '<script>alert("XSS")</script>')
    
    template = 'Content: {{ content }}'
    result = engine.render(template)
    
    # Check that HTML is escaped
    assert '&lt;' in result, "< should be escaped to &lt;"
    assert '&gt;' in result, "> should be escaped to &gt;"
    assert '&quot;' in result, '" should be escaped to &quot;'
    assert '<script>' not in result, "Raw HTML tags should not appear"
    assert 'alert' in result, "Content should still be present (escaped)"


def test_undefined_variables_preserved():
    """Test that undefined variables are preserved in output"""
    engine = TemplateEngine()
    engine.set_variable('defined', 'value')
    
    template = 'Defined: {{ defined }}, Undefined: {{ undefined }}'
    result = engine.render(template)
    
    assert 'value' in result, "Defined variable should be substituted"
    assert '{{ undefined }}' in result, "Undefined variable placeholder should be preserved"


def test_render_with_context_preserves_variables():
    """Test that render_with_context merges instead of replacing variables"""
    engine = TemplateEngine()
    engine.set_variable('global_var', 'global')
    
    template = 'Global: {{ global_var }}, Local: {{ local_var }}'
    result = engine.render_with_context(template, {'local_var': 'local'})
    
    assert 'global' in result, "Global variable should still be available"
    assert 'local' in result, "Local variable from context should be available"
    
    # After render_with_context, global_var should still be set
    template2 = 'Still global: {{ global_var }}'
    result2 = engine.render(template2)
    assert 'global' in result2, "Global variable should persist after render_with_context"


def test_manual_escape_html_complete():
    """Test that manual HTML escaping includes all special characters"""
    engine = TemplateEngine()
    
    # Test all special characters
    test_string = '&<>"\''
    escaped = engine.escape_html(test_string)
    
    assert '&amp;' in escaped, "& should be escaped"
    assert '&lt;' in escaped, "< should be escaped"
    assert '&gt;' in escaped, "> should be escaped"
    assert '&quot;' in escaped, '" should be escaped'
    assert '&#x27;' in escaped or '&#39;' in escaped or '&apos;' in escaped, "' should be escaped"
    assert '<' not in escaped.replace('&lt;', ''), "Raw < should not appear"


def test_render_file_basic():
    """Test that rendering from file works correctly"""
    engine = TemplateEngine()
    engine.set_variable('title', 'Test Page')
    engine.set_variable('name', 'Bob')
    
    result = engine.render_file('/app/templates/basic.html')
    
    assert 'Test Page' in result, "Title variable should be substituted"
    assert 'Bob' in result, "Name variable should be substituted"
    assert '<!DOCTYPE html>' in result, "HTML structure should be preserved"
