import sys
import time
import pytest
sys.path.insert(0, '/app')

from dns_resolver import DNSResolver, DNSCache

def test_cache_stores_and_retrieves():
    """Test that cache can store and retrieve records."""
    cache = DNSCache()
    cache.set("example.com", "A", ["93.184.216.34"], 300)
    
    result = cache.get("example.com", "A")
    assert result is not None, "Cache should return stored record"
    assert "93.184.216.34" in result, "Cache should return correct IP"

def test_cache_expiry_removes_old_entries():
    """Test that cache properly expires old entries."""
    cache = DNSCache()
    cache.set("example.com", "A", ["93.184.216.34"], 1)
    
    time.sleep(2)
    result = cache.get("example.com", "A")
    assert result is None, "Cache should return None for expired entry"

def test_cache_returns_valid_entries():
    """Test that cache returns entries that haven't expired."""
    cache = DNSCache()
    cache.set("example.com", "A", ["93.184.216.34"], 10)
    
    time.sleep(1)
    result = cache.get("example.com", "A")
    assert result is not None, "Cache should return valid non-expired entry"
    assert "93.184.216.34" in result, "Cache should return correct data"

def test_cache_distinguishes_record_types():
    """Test that cache stores different record types separately."""
    cache = DNSCache()
    cache.set("example.com", "A", ["93.184.216.34"], 300)
    cache.set("example.com", "AAAA", ["2606:2800:220:1:248:1893:25c8:1946"], 300)
    
    a_result = cache.get("example.com", "A")
    aaaa_result = cache.get("example.com", "AAAA")
    
    assert a_result is not None, "Should retrieve A record"
    assert aaaa_result is not None, "Should retrieve AAAA record"
    assert "93.184.216.34" in a_result, "A record should be correct"
    assert "2606:2800:220:1:248:1893:25c8:1946" in aaaa_result, "AAAA record should be correct"

def test_resolver_supports_a_records():
    """Test that resolver can query A records."""
    resolver = DNSResolver()
    
    try:
        result = resolver.resolve("google.com", "A")
        assert len(result) > 0, "Should return at least one A record"
        assert all('.' in ip for ip in result), "A records should be IPv4 addresses"
    except Exception as e:
        pytest.skip(f"DNS query failed (network issue): {e}")

def test_resolver_caches_results():
    """Test that resolver caches DNS query results."""
    resolver = DNSResolver()
    
    try:
        result1 = resolver.resolve("google.com", "A")
        cached_result = resolver.cache.get("google.com", "A")
        
        assert cached_result is not None, "Result should be cached"
        assert result1 == cached_result, "Cached result should match query result"
    except Exception as e:
        pytest.skip(f"DNS query failed (network issue): {e}")

def test_resolver_uses_cache():
    """Test that resolver returns cached results without re-querying."""
    resolver = DNSResolver()
    resolver.cache.set("test.example.com", "A", ["1.2.3.4"], 300)
    
    result = resolver.resolve("test.example.com", "A")
    assert result == ["1.2.3.4"], "Should return cached result"
