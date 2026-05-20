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
# 启动前杀掉所有旧进程（防止叠加）
ExecStartPre=/usr/bin/pkill -9 -f "python.*web_app.py"
ExecStartPre=/usr/bin/sleep 2
ExecStart=/usr/bin/python3 web_app.py
Restart=always
RestartSec=30
MemoryMax=2.5G
# 内存警告阈值（超过2G时警告）
MemoryHigh=2G

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