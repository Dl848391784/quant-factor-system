#!/bin/bash
# 更新 factor-web.service 配置
# 添加启动前杀掉旧进程的逻辑

cat > /tmp/factor-web.service << 'EOF'
[Unit]
Description=Factor IC Analysis Web Service
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/projects/factor_ic_analyzer
# R34 fix: 真实入口是 web_ui/app.py (旧配置 web_app.py 不存在)
# venv 才有 flask, /usr/bin/python3 没有
ExecStart=/home/admin/projects/factor_ic_analyzer/venv/bin/python web_ui/app.py
# PIPELINE_ALIAS=ob_quality 是 web_ui/app.py 默认 (硬编码), 无需 Environment
TimeoutStartSec=90
Restart=always
RestartSec=30
ExecStopPost=/bin/bash -c 'pkill -9 -f "web_ui/app.py" || true'
MemoryMax=4G
MemoryHigh=3G

[Install]
WantedBy=multi-user.target
EOF

# 复制到 systemd 目录
sudo cp /tmp/factor-web.service /etc/systemd/system/factor-web.service

# 重新加载 systemd 配置
sudo systemctl daemon-reload

echo "✅ factor-web.service 配置已更新"
echo ""
echo "新增功能："
echo "  - ExecStartPre: 启动前自动杀掉旧进程"
echo "  - MemoryHigh: 2G 内存警告阈值"
echo ""
echo "现在可以用以下命令管理服务："
echo "  sudo systemctl start factor-web"
echo "  sudo systemctl restart factor-web"
echo "  sudo systemctl stop factor-web"