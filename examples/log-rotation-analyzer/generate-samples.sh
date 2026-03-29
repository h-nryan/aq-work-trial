#!/bin/bash

echo "Generating sample data for log-rotation-analyzer task..."

mkdir -p sample_logs sample_configs

echo "Creating sample log files with different rotation states..."

# large unrotated application log
echo "Generating large application log..."
{
    for i in {1..1000}; do
        echo "$(date -d "$i hours ago" '+%Y-%m-%d %H:%M:%S') [INFO] Application server started successfully"
        echo "$(date -d "$i hours ago" '+%Y-%m-%d %H:%M:%S') [ERROR] Database connection timeout after 30 seconds"
        echo "$(date -d "$i hours ago" '+%Y-%m-%d %H:%M:%S') [WARN] Memory usage at 85% - consider scaling"
        echo "$(date -d "$i hours ago" '+%Y-%m-%d %H:%M:%S') [DEBUG] Processing batch job #$i"
    done
} > sample_logs/app.log

# properly rotated system log
echo "Creating properly rotated system log..."
echo "$(date '+%Y-%m-%d %H:%M:%S') systemd[1]: Started Update UTMP about System Boot/Shutdown" > sample_logs/system.log
echo "$(date '+%Y-%m-%d %H:%M:%S') kernel: [    0.000000] Linux version 5.4.0" >> sample_logs/system.log
echo "$(date '+%Y-%m-%d %H:%M:%S') NetworkManager[1234]: <info> device (eth0): state change" >> sample_logs/system.log

# create a rotated version
{
    for i in {1..100}; do
        echo "$(date -d "$((i+24)) hours ago" '+%Y-%m-%d %H:%M:%S') systemd[1]: Previous day system message $i"
    done
} > sample_logs/system.log.1
gzip sample_logs/system.log.1

# high-volume access logs (should need daily rotation)
echo "Creating high-volume access logs..."
{
    for i in {1..2000}; do
        ips=("192.168.1.10" "10.0.0.5" "172.16.0.100" "203.0.113.45")
        methods=("GET" "POST" "PUT" "DELETE")
        codes=("200" "201" "400" "404" "500")
        paths=("/api/users" "/api/orders" "/api/products" "/health" "/metrics")
        
        ip=${ips[$((i % 4))]}
        method=${methods[$((i % 4))]}
        path=${paths[$((i % 5))]}
        code=${codes[$((i % 5))]}
        size=$((RANDOM % 5000 + 100))
        
        echo "$ip - - [$(date -d "$i minutes ago" '+%d/%b/%Y:%H:%M:%S %z')] \"$method $path HTTP/1.1\" $code $size"
    done
} > sample_logs/access.log

# create old access log that should have been rotated
{
    for i in {1..500}; do
        echo "127.0.0.1 - - [$(date -d "$((i+48)) hours ago" '+%d/%b/%Y:%H:%M:%S %z')] \"GET /old/endpoint HTTP/1.1\" 200 1234"
    done
} > sample_logs/access.log.old

# error log that's never been rotated
echo "Creating unrotated error log..."
{
    for i in {1..3000}; do
        error_types=("OutOfMemoryError" "ConnectionTimeout" "FileNotFound" "DatabaseError" "AuthenticationFailure")
        error_type=${error_types[$((i % 5))]}
        
        echo "[$(date -d "$i minutes ago" '+%Y-%m-%d %H:%M:%S')] FATAL: $error_type in module core.processor line $((RANDOM % 1000 + 1))"
    done
} > sample_logs/error.log

# debug log with mixed rotation
echo "Creating debug log..."
{
    for i in {1..800}; do
        echo "$(date -d "$((i*2)) minutes ago" '+%Y-%m-%d %H:%M:%S') DEBUG [thread-$((i % 10))] Processing request ID: req_$i"
    done
} > sample_logs/debug.log

echo "Creating sample logrotate configurations..."

# create sample logrotate configs
cat > sample_configs/app << 'EOF'
/var/log/samples/app.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
EOF

cat > sample_configs/system << 'EOF'
/var/log/samples/system.log {
    weekly
    rotate 4
    compress
    delaycompress
    missingok
    create 644 root adm
}
EOF

cat > sample_configs/access << 'EOF'
/var/log/samples/access.log {
    monthly
    rotate 2
    compress
    missingok
}
EOF

echo "Creating metadata file..."

# create metadata file
cat > log_metadata.json << 'EOF'
{
  "logs": [
    {
      "path": "/var/log/samples/app.log",
      "type": "application",
      "importance": "high",
      "growth_rate_mb_per_day": 15.2,
      "retention_requirement_days": 30,
      "application": "web-server",
      "owner": "www-data"
    },
    {
      "path": "/var/log/samples/system.log", 
      "type": "system",
      "importance": "critical",
      "growth_rate_mb_per_day": 2.1,
      "retention_requirement_days": 90,
      "application": "systemd",
      "owner": "root"
    },
    {
      "path": "/var/log/samples/access.log",
      "type": "access",
      "importance": "medium", 
      "growth_rate_mb_per_day": 45.7,
      "retention_requirement_days": 14,
      "application": "nginx",
      "owner": "www-data"
    },
    {
      "path": "/var/log/samples/error.log",
      "type": "error",
      "importance": "critical",
      "growth_rate_mb_per_day": 8.9,
      "retention_requirement_days": 60,
      "application": "web-server",
      "owner": "www-data"
    },
    {
      "path": "/var/log/samples/debug.log",
      "type": "debug",
      "importance": "low",
      "growth_rate_mb_per_day": 5.3,
      "retention_requirement_days": 7,
      "application": "web-server",
      "owner": "www-data"
    }
  ],
  "system_info": {
    "available_disk_gb": 50,
    "log_partition_usage_percent": 78,
    "backup_frequency": "daily",
    "compliance_requirements": ["PCI-DSS", "SOX"],
    "peak_traffic_hours": ["09:00-11:00", "14:00-16:00", "20:00-22:00"]
  },
  "current_issues": [
    "High disk usage on log partition",
    "Inconsistent rotation schedules",
    "Missing compression on some logs",
    "Some critical logs lack rotation configuration"
  ]
}
EOF

echo ""
echo "Sample data generation completed successfully!"
echo ""
echo "Generated files:"
echo "  Sample logs:"
echo "    - sample_logs/app.log (large, unrotated application log)"
echo "    - sample_logs/system.log (properly rotated system log)"
echo "    - sample_logs/access.log (high-volume access log)"
echo "    - sample_logs/error.log (unrotated error log)"
echo "    - sample_logs/debug.log (debug log with mixed rotation)"
echo ""
echo "  Sample configs:"
echo "    - sample_configs/app (suboptimal app log config)"
echo "    - sample_configs/system (decent system log config)"
echo "    - sample_configs/access (poor access log config)"
echo "    - Note: error.log has no config (intentional issue)"
echo ""
echo "  Metadata:"
echo "    - log_metadata.json (comprehensive system and log information)"
echo ""
echo "Your task environment is now ready for testing!"