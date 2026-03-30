#!/bin/bash
set -euo pipefail

# Fix all bugs in the DNS resolver
cat > /app/dns_resolver.py << 'EOF'
#!/usr/bin/env python3
import socket
import struct
import time
import random
from typing import Dict, List, Tuple, Optional

class DNSCache:
    def __init__(self):
        self.cache: Dict[Tuple[str, str], Tuple[List[str], float]] = {}
    
    def get(self, domain: str, record_type: str) -> Optional[List[str]]:
        key = (domain, record_type)
        if key in self.cache:
            records, expiry = self.cache[key]
            if time.time() < expiry:
                return records
            del self.cache[key]
        return None
    
    def set(self, domain: str, record_type: str, records: List[str], ttl: int):
        key = (domain, record_type)
        expiry = time.time() + ttl
        self.cache[key] = (records, expiry)

class DNSResolver:
    def __init__(self, nameserver: str = "8.8.8.8", port: int = 53):
        self.nameserver = nameserver
        self.port = port
        self.cache = DNSCache()
        self.type_map = {"A": 1, "AAAA": 28, "MX": 15, "CNAME": 5, "TXT": 16}
    
    def build_query(self, domain: str, qtype: int) -> bytes:
        transaction_id = random.randint(0, 65535)
        flags = 0x0100
        questions = 1
        answer_rrs = 0
        authority_rrs = 0
        additional_rrs = 0
        
        header = struct.pack(">HHHHHH", transaction_id, flags, questions,
                            answer_rrs, authority_rrs, additional_rrs)
        
        question = b""
        for part in domain.split("."):
            question += struct.pack("B", len(part)) + part.encode()
        question += b"\x00"
        question += struct.pack(">HH", qtype, 1)
        
        return header + question
    
    def parse_response(self, response: bytes, qtype: int) -> Tuple[List[str], int]:
        header = response[:12]
        _, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", header)
        
        if flags & 0x000F != 0:
            raise Exception("DNS query failed")
        
        offset = 12
        for _ in range(qdcount):
            while response[offset] != 0:
                offset += response[offset] + 1
            offset += 5
        
        records = []
        ttl = 300
        
        for _ in range(ancount):
            name_offset = offset
            while response[offset] != 0:
                if response[offset] & 0xC0 == 0xC0:
                    offset += 2
                    break
                offset += response[offset] + 1
            else:
                offset += 1
            
            rtype, rclass, rttl, rdlength = struct.unpack(">HHIH", response[offset:offset+10])
            offset += 10
            rdata = response[offset:offset+rdlength]
            offset += rdlength
            
            if rtype == qtype:
                ttl = rttl
                if qtype == 1:
                    records.append(socket.inet_ntoa(rdata))
                elif qtype == 28:
                    records.append(socket.inet_ntop(socket.AF_INET6, rdata))
                elif qtype == 5:
                    name = self._parse_name(response, offset - rdlength)
                    records.append(name)
                elif qtype == 15:
                    priority = struct.unpack(">H", rdata[:2])[0]
                    name = self._parse_name(response, offset - rdlength + 2)
                    records.append(f"{priority} {name}")
                elif qtype == 16:
                    txt = rdata[1:].decode('utf-8', errors='ignore')
                    records.append(txt)
        
        return records, ttl
    
    def _parse_name(self, response: bytes, offset: int) -> str:
        parts = []
        while response[offset] != 0:
            if response[offset] & 0xC0 == 0xC0:
                pointer = struct.unpack(">H", response[offset:offset+2])[0] & 0x3FFF
                parts.append(self._parse_name(response, pointer))
                break
            length = response[offset]
            offset += 1
            parts.append(response[offset:offset+length].decode())
            offset += length
        return ".".join(parts)
    
    def resolve(self, domain: str, record_type: str = "A") -> List[str]:
        record_type = record_type.upper()
        if record_type not in self.type_map:
            raise ValueError(f"Unsupported record type: {record_type}")
        
        cached = self.cache.get(domain, record_type)
        if cached:
            return cached
        
        qtype = self.type_map[record_type]
        query = self.build_query(domain, qtype)
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        sock.sendto(query, (self.nameserver, self.port))
        response, _ = sock.recvfrom(4096)
        sock.close()
        
        records, ttl = self.parse_response(response, qtype)
        self.cache.set(domain, record_type, records, ttl)
        
        return records
EOF

chmod +x /app/dns_resolver.py
