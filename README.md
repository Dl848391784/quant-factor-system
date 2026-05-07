# 因子池 IC 分析系统

**作者**: 云舟  
**版本**: v1.0.0  
**日期**: 2026-04-01

## 功能概述

计算因子 Rank IC（秩相关系数）并生成可视化报告，用于评估因子的预测能力。

## 系统架构

```
factor_ic_analyzer/
├── __init__.py         # 包初始化
├── main.py             # 主程序入口
├── data_loader.py      # 数据加载模块
├── ic_calculator.py     # IC计算模块
├── visualizer.py       # 可视化模块
├── web_app.py          # Web应用 (新增)
├── export_results.py   # 导出JSON (新增)
├── start_web.sh        # Web启动脚本 (新增)
├── ic_results.json     # IC结果数据 (新增)
├── requirements.txt    # 依赖包
├── README.md           # 本文件
├── templates/          # Web模板 (新增)
│   ├── index.html      # 主页
│   └── compare.html    # 对比页
└── output/             # 输出目录
```

## 核心模块

### 1. DataLoader (data_loader.py)
- 支持模拟数据生成
- 预留真实数据接口
- 自动数据清洗

### 2. ICCalculator (ic_calculator.py)
- **Rank IC**: 使用 Spearman 秩相关系数
- **统计指标**: IC均值、IC标准差、ICIR、t统计量、IC>0占比
- **布尔因子处理**: 自动转换为 0/1 值

### 3. ICVisualizer (visualizer.py)
- IC时序折线图
- IC分布直方图
- 多因子对比图
- 统计信息标注

## 使用方法

```bash
# 安装依赖
pip install -r requirements.txt

# 运行分析（生成图表）
python main.py

# 启动Web界面
bash start_web.sh
# 或
python web_app.py
```

## Web界面

访问 http://localhost:8765 查看可视化结果：

- **概览页面**: 展示统计指标和IC图表
- **因子对比**: 多因子关键指标对比
- **API接口**: `/api/results` 获取JSON数据

## 因子说明

当前分析两个布尔因子：

| 因子 | 定义 | 预期方向 |
|------|------|----------|
| RSI超卖 | RSI(6) < 30 | 正向（反转效应） |
| 量比放大 | 量比 > 1.5 | 反向（放量见顶） |

## 输出示例

### 控制台输出
```
【rsi_oversold】
  IC均值:     0.0342
  IC标准差:   0.1120
  ICIR:       0.3054
  t统计量:    8.3541
  IC>0占比:   56.8%
  因子评级:   C级 (一般)
```

### 生成图表
- `{factor}_ic_series.png`: IC时序图
- `factors_ic_comparison.png`: 多因子对比图
- `{factor}_ic_distribution.png`: IC分布图

## 因子评级标准

| 等级 | ICIR | 评价 |
|------|------|------|
| A级 | > 1.0 | 优秀，可直接使用 |
| B级 | > 0.5 | 良好，可考虑使用 |
| C级 | > 0.3 | 一般，需谨慎 |
| D级 | < 0.3 | 较弱，不建议使用 |

## 扩展说明

### 添加新因子
在 `DataLoader.load_simulated_data()` 中添加新因子列，然后在 `main.py` 的 `factor_names` 列表中添加因子名称。

### 接入真实数据
修改 `DataLoader` 类，实现以下方法：
- `load_real_data()`: 从数据库或文件加载真实数据
- 确保数据格式：MultiIndex (date, stock)，列为因子值

## 技术要点

1. **Rank IC计算**: 使用 `scipy.stats.spearmanr()` 计算秩相关系数
2. **布尔因子处理**: 直接转换为 0/1 值，Spearman相关可处理
3. **统计显著性**: t统计量 > 2 表示在95%置信水平显著
4. **移动平均**: 20日MA用于观察IC趋势

## 注意事项

- 当前使用模拟数据演示功能
- 真实数据需处理停牌、涨跌停等特殊情况
- 布尔因子IC通常较低，属正常现象

---

*代码实现: 云舟 🛠️*