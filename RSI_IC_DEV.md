# RSI(6) Rank IC 折线图开发说明

## 开发内容

扩展了 `factor_ic_analyzer` 网页应用，新增 RSI(6) IC 时间序列展示页面。

## 新增文件

1. **rsi_ic_generator.py** - RSI 模拟数据生成器
   - 生成过去750个交易日的 RSI(6) 因子数据（100只股票）
   - 计算每日反向排名 Rank IC
   - 保存为 `rsi_ic_data.json`

2. **templates/rsi_ic.html** - IC 折线图网页模板
   - Chart.js 绘制 IC 时间序列折线图
   - 显示每日 IC 和 20日滚动均值
   - 统计指标卡片：IC均值、ICIR、正比例、IC标准差等

3. **web_app.py** - 更新路由
   - `/rsi-ic` - RSI IC 折线图页面
   - `/api/rsi-ic` - API 接口返回 JSON 数据

## 技术方案

- **前端**：Chart.js 绘制交互式折线图，自动采样显示（每5个点）
- **后端**：Flask 提供 API 接口
- **数据**：使用 `reverse_rank_ic.py` 计算反向排名 IC

## 访问方式

- **网页**：http://localhost:8765/rsi-ic
- **API**：http://localhost:8765/api/rsi-ic

## 当前数据统计

- IC均值：0.2296
- ICIR：2.28
- 正比例：98.8%
- 交易日数：750
- 股票数量：100

## 说明

数据为模拟数据，用于演示 IC 时间序列可视化效果。实际使用时可替换为真实因子数据。

---
开发时间：2026-04-01
开发者：云舟