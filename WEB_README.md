# Web 界面使用说明

## 快速启动

```bash
# 方式1: 使用启动脚本
cd factor_ic_analyzer
bash start_web.sh

# 方式2: 直接运行
python web_app.py
```

## 访问地址

- 主页（概览）: http://localhost:8765
- 因子对比: http://localhost:8765/compare
- API接口: http://localhost:8765/api/results

## 功能

1. **概览页面**
   - 显示两个因子的统计指标卡片
   - IC时序图切换查看
   - IC分布图展示

2. **因子对比页面**
   - 关键指标对比表格
   - 综合评分展示
   - 多因子IC对比图

## 目录结构

```
factor_ic_analyzer/
├── web_app.py              # Flask应用
├── start_web.sh            # 启动脚本
├── ic_results.json         # IC分析结果数据
├── templates/
│   ├── index.html          # 主页模板
│   └── compare.html        # 对比页模板
├── output/                 # 图表输出目录
│   ├── rsi_oversold_ic_series.png
│   ├── rsi_oversold_ic_distribution.png
│   ├── volume_ratio_high_ic_series.png
│   ├── volume_ratio_high_ic_distribution.png
│   └── factors_ic_comparison.png
└── static/                 # 静态资源（如需要）
```

## 更新数据

当运行 `main.py` 重新计算IC后，需要更新 `ic_results.json` 文件。
可以通过修改 `main.py` 添加自动导出JSON功能：

```python
import json

# 在 main() 函数最后添加
output_json = output_dir / 'ic_results.json'
json_data = {}
for factor_name, result in calculator.ic_results.items():
    json_data[factor_name] = {
        'statistics': result['statistics'],
        'description': '因子描述',
        'grade': '评级'
    }
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(json_data, f, indent=2)
```

## 技术栈

- 后端: Flask
- 前端: 纯HTML + CSS + JavaScript
- 图表: 已生成的PNG图片
- 端口: 8765