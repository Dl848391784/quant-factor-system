# 因子池 IC 分析系统开发说明

**开发者**: 云舟 🛠️  
**日期**: 2026-04-01  
**状态**: ✅ 开发完成，待测试

---

## 一、已交付文件

```
factor_ic_analyzer/
├── __init__.py         (244 bytes)  包初始化
├── main.py             (1.5 KB)     主程序入口
├── data_loader.py      (4.5 KB)     数据加载模块
├── ic_calculator.py    (7.8 KB)     IC计算模块
├── visualizer.py       (9.2 KB)     可视化模块
├── requirements.txt    (75 bytes)   依赖列表
├── README.md           (1.8 KB)     使用说明
└── output/             (557 KB)     生成的图表
    ├── rsi_oversold_ic_series.png
    ├── volume_ratio_high_ic_series.png
    ├── factors_ic_comparison.png
    ├── rsi_oversold_ic_distribution.png
    └── volume_ratio_high_ic_distribution.png
```

---

## 二、功能实现

### 2.1 数据加载 (data_loader.py)
- ✅ 模拟数据生成：100只股票，750交易日
- ✅ 因子1：RSI超卖因子 (RSI(6) < 30)
- ✅ 因子2：量比因子 (量比 > 1.5)
- ✅ 布尔因子转换为0/1值
- ✅ 预留真实数据接口

### 2.2 IC计算 (ic_calculator.py)
- ✅ Spearman秩相关系数计算Rank IC
- ✅ 每日IC序列计算（750个交易日）
- ✅ 统计指标：
  - IC均值
  - IC标准差
  - ICIR (Information Ratio)
  - t统计量
  - IC>0占比
- ✅ 因子评级（A/B/C/D级）

### 2.3 可视化 (visualizer.py)
- ✅ IC时序折线图（含柱状图+移动平均）
- ✅ IC分布直方图（含核密度估计）
- ✅ 多因子对比图（纵向排列）
- ✅ 统计信息标注

---

## 三、运行结果

### 3.1 RSI超卖因子 (rsi_oversold)
```
IC均值:     0.0542   (正向因子，超卖反转效应)
IC标准差:   0.1026
ICIR:       0.5284   (>0.5，稳定性良好)
t统计量:    14.47    (>2，显著有效)
IC>0占比:   70.53%   (预测准确率较高)
评级:       B级 (良好)
```

### 3.2 量比因子 (volume_ratio_high)
```
IC均值:     -0.0338  (反向因子，放量可能见顶)
IC标准差:   0.1010
ICIR:       -0.3347  (稳定性一般)
t统计量:    -9.17    (显著)
IC>0占比:   36.40%   (反向有效)
评级:       C级 (一般)
```

---

## 四、技术要点

### 4.1 Rank IC计算
- 使用 `scipy.stats.spearmanr()` 计算秩相关
- 自动剔除NaN值和无效样本
- 样本数<5时返回NaN避免误算

### 4.2 布尔因子处理
- 布尔值0/1直接用于排名计算
- Spearman方法天然支持二值变量
- 无需额外转换步骤

### 4.3 统计显著性
- ICIR = IC均值 / IC标准差（衡量稳定性）
- t统计量 = IC均值 / (IC标准差/sqrt(n))
- t>2 表示95%置信水平显著

### 4.4 可视化优化
- 使用英文标签避免字体问题
- Agg后端生成PNG图片
- 柱状图区分正负IC（绿/红）
- 20日移动平均线显示趋势

---

## 五、依赖环境

已验证的Python环境：
- Python 3.6.8
- numpy (已有)
- scipy 1.5.4 ✅
- matplotlib 3.3.4 ✅
- pandas (已有)
- kiwisolver 1.3.1 ✅
- pillow 6.2.2 ✅

安装命令：
```bash
python3 -m pip install scipy matplotlib kiwisolver pillow -i https://pypi.tuna.tsinghua.edu.cn/simple --user
```

---

## 六、运行方法

```bash
cd yunzhou/factor_ic_analyzer
MPLBACKEND=Agg python3 main.py
```

---

## 七、待云汐测试项

1. **数据模块测试**
   - 缺失值处理是否正确
   - 不同股票数量下的表现
   - 时间范围调整

2. **IC计算测试**
   - 边界情况（少量样本）
   - NaN处理是否合理
   - 统计指标准确性

3. **可视化测试**
   - 图片是否清晰
   - 统计信息是否准确标注
   - 多因子对比是否直观

4. **扩展测试**
   - 添加新因子是否方便
   - 参数调整是否灵活
   - 真实数据接口预留是否合理

---

## 八、扩展建议

后续可扩展功能：
1. 真实A股数据接入（需数据接口）
2. 不同预测周期（3日/10日/20日收益）
3. 滚动IC观察趋势变化
4. 行业中性IC计算
5. 分层回测验证因子效果

---

*开发完成，交付测试*  
*云舟 🛠️*