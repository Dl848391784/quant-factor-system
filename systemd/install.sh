#!/bin/bash
# 因子优化预计算 systemd 服务安装脚本
# 作者: 云舟 🛠️

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="factor-optimizer"
SERVICE_FILE="$SCRIPT_DIR/${SERVICE_NAME}.service"
TIMER_FILE="$SCRIPT_DIR/${SERVICE_NAME}.timer"

echo "=========================================="
echo "因子优化预计算 systemd 服务安装"
echo "=========================================="

# 检查文件是否存在
if [ ! -f "$SERVICE_FILE" ]; then
    echo "错误: 找不到服务文件 $SERVICE_FILE"
    exit 1
fi

if [ ! -f "$TIMER_FILE" ]; then
    echo "错误: 找不到定时器文件 $TIMER_FILE"
    exit 1
fi

# 复制文件到 systemd 目录
echo "1. 复制服务文件到 systemd 目录..."
sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo cp "$TIMER_FILE" /etc/systemd/system/

# 重新加载 systemd
echo "2. 重新加载 systemd 配置..."
sudo systemctl daemon-reload

# 启用定时器（不启用服务，服务由定时器触发）
echo "3. 启用定时器..."
sudo systemctl enable ${SERVICE_NAME}.timer

# 显示状态
echo "4. 查看定时器状态..."
sudo systemctl list-timers ${SERVICE_NAME}.timer

echo ""
echo "=========================================="
echo "安装完成！"
echo "=========================================="
echo ""
echo "服务信息:"
echo "  - 服务名称: ${SERVICE_NAME}"
echo "  - 执行时间: 每天凌晨 02:00"
echo "  - 日志文件: /home/admin/projects/factor_ic_analyzer/logs/optimizer.log"
echo ""
echo "常用命令:"
echo "  # 查看定时器状态"
echo "  sudo systemctl status ${SERVICE_NAME}.timer"
echo ""
echo "  # 查看下次执行时间"
echo "  sudo systemctl list-timers ${SERVICE_NAME}.timer"
echo ""
echo "  # 手动触发一次计算"
echo "  sudo systemctl start ${SERVICE_NAME}.service"
echo ""
echo "  # 查看计算日志"
echo "  tail -f /home/admin/projects/factor_ic_analyzer/logs/optimizer.log"
echo ""
echo "  # 停止定时器"
echo "  sudo systemctl stop ${SERVICE_NAME}.timer"
echo ""
echo "  # 禁用定时器"
echo "  sudo systemctl disable ${SERVICE_NAME}.timer"
echo ""