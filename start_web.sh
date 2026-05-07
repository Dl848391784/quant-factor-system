#!/bin/bash
# 因子池 IC 分析系统 - Web界面启动脚本
# 作者: 云舟

cd "$(dirname "$0")"

echo "============================================================"
echo "因子池 IC 分析系统 - Web界面启动"
echo "============================================================"
echo ""
echo "访问地址: http://localhost:8765"
echo ""
echo "提示:"
echo "  - 按 Ctrl+C 停止服务"
echo "  - 确保已安装依赖: pip install flask"
echo ""

# 检查依赖
python3 -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "错误: 未安装 Flask"
    echo "请运行: pip install flask"
    exit 1
fi

# 启动Web服务
python3 web_app.py