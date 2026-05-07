# 因子组合优化预计算系统 - 开发报告

**开发者**: 云舟 🛠️
**完成时间**: 2026-04-14
**任务来源**: `/home/admin/.openclaw/workspace/yunbai/tasks/factor_optimizer_precompute.md`

---

## 一、开发完成情况

### Phase 1: 核心预计算模块 ✅ 完成

创建了预计算主程序，实现：
- 零侵入设计：不修改现有核心模块
- 全复用：直接调用 weight_optimizer、quick_backtest、scoring_engine
- 内存友好：内存检查、GC清理、线程池替代进程池
- 原子写入：结果文件写入完整性保障

**创建文件**:
```
/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/precompute_optimizer.py
```

**核心功能**:
1. `run_precompute()` - 执行预计算流程（网格搜索 → 回测验证 → 股票推荐）
2. `get_precompute_result()` - 获取预计算结果
3. `get_top_stocks(n)` - 获取推荐股票（支持数量参数）
4. `get_precompute_status()` - 获取计算状态
5. 历史记录管理（保留近7天）
6. 内存检查和容错机制

---

### Phase 2: API 接口 ✅ 完成

在 web_app.py 中新增 5 个 API 路由：

**API 端点**:
| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/precompute/optimization-result` | GET | 获取最优组合结果 |
| `/api/precompute/top-stocks?n=3` | GET | 获取推荐股票（支持数量1-20） |
| `/api/precompute/status` | GET | 查询计算状态 |
| `/api/precompute/trigger` | POST | 手动触发计算 |
| `/api/precompute/history` | GET | 获取历史记录（近7天） |

**修改文件**:
```
/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/web_app.py
```

---

### Phase 3: 前端展示 ✅ 完成

在选股页面顶部新增预计算结果卡片：

**功能展示**:
1. 最优策略指标（年化收益、夏普比率、最大回撤、胜率）
2. 权重可视化条形图（正向/反向因子颜色区分）
3. 推荐股票表格（Top 3）
4. "应用此策略"按钮（一键填充权重）
5. 新鲜度标识（24小时内为"新鲜"，否则"过期"）
6. 手动触发计算功能（管理员）

**修改文件**:
```
/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/templates/stock_scoring.html
```

**新增样式**: 约 250 行 CSS
**新增脚本**: 约 200 行 JavaScript

---

### Phase 4: 定时任务配置 ✅ 完成

创建 systemd 服务和定时器：

**创建文件**:
```
/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/systemd/
├── factor-optimizer.service   # 服务单元
├── factor-optimizer.timer     # 定时器单元
└── install.sh                 # 安装脚本
```

**配置详情**:
- 执行时间: 每天凌晨 02:00
- 内存限制: Max 2GB, High 1.5GB
- CPU限制: 80%
- 超时: 3小时
- 随机延迟: 0-5分钟

---

## 二、文件清单

| 文件 | 类型 | 大小 | 说明 |
|------|------|------|------|
| `precompute_optimizer.py` | 新增 | 22KB | 预计算主程序 |
| `web_app.py` | 修改 | +10KB | 新增 5 个 API 路由 |
| `templates/stock_scoring.html` | 修改 | +15KB | 前端卡片和脚本 |
| `systemd/factor-optimizer.service` | 新增 | 1KB | systemd 服务配置 |
| `systemd/factor-optimizer.timer` | 新增 | 0.4KB | systemd 定时器 |
| `systemd/install.sh` | 新增 | 2KB | 安装脚本 |
| `cache/precompute/` | 新增目录 | - | 结果存储目录 |

---

## 三、数据流说明

```
┌─────────────────────────────────────────────────────────────┐
│                    凌晨预计算流程                            │
├─────────────────────────────────────────────────────────────┤
│  02:00  systemd timer 触发                                  │
│    ↓                                                        │
│  precompute_optimizer.py                                    │
│    ↓                                                        │
│  Step 1: 网格搜索 (weight_optimizer.py)                     │
│    - 收集 Top 100 候选组合                                   │
│    ↓                                                        │
│  Step 2: 回测验证 (quick_backtest.py)                       │
│    - 线程池并行处理（内存友好）                              │
│    ↓                                                        │
│  Step 3: 筛选最优组合                                        │
│    - 年化收益最高                                            │
│    ↓                                                        │
│  Step 4: 计算推荐股票 (scoring_engine.py)                   │
│    - 使用最优权重打分                                        │
│    - Top 20 股票（API 按需取用）                             │
│    ↓                                                        │
│  Step 5: 原子写入 JSON                                       │
│    - cache/precompute/optimization_result.json              │
│    - cache/precompute/top_stocks.json                       │
│    ↓                                                        │
│  完成（约 2.5 小时）                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    用户访问流程                              │
├─────────────────────────────────────────────────────────────┤
│  用户打开选股页面                                           │
│    ↓                                                        │
│  前端调用 /api/precompute/optimization-result               │
│    ↓                                                        │
│  直接读取 JSON 文件（无实时计算）                            │
│    ↓                                                        │
│  展示最优策略卡片                                           │
│    ↓                                                        │
│  用户点击"应用此策略"                                       │
│    ↓                                                        │
│  权重自动填充到表单                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、部署说明

### 4.1 安装定时任务

```bash
cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/systemd
sudo ./install.sh
```

### 4.2 验证安装

```bash
# 查看定时器状态
sudo systemctl status factor-optimizer.timer

# 查看下次执行时间
sudo systemctl list-timers factor-optimizer.timer
```

### 4.3 手动触发测试

```bash
# 手动执行一次
sudo systemctl start factor-optimizer.service

# 查看日志
tail -f /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/logs/optimizer.log
```

---

## 五、测试建议（给云汐）

### 5.1 功能测试

| 测试项 | 操作 | 预期结果 |
|--------|------|----------|
| TC01 | 手动触发预计算 | 成功生成结果文件 |
| TC02 | 调用 `/api/precompute/status` | 返回正确状态 |
| TC03 | 调用 `/api/precompute/top-stocks?n=5` | 返回5只股票 |
| TC04 | 打开选股页面 | 显示最优策略卡片 |
| TC05 | 点击"应用此策略" | 权重自动填充 |
| TC06 | 内存不足场景 | 优雅跳过不崩溃 |
| TC07 | 无结果状态 | 显示空状态卡片 |

### 5.2 性能测试

- 内存峰值是否低于 2GB
- 计算耗时是否在 3 小时内
- API 响应是否低于 100ms

### 5.3 回归测试

- 现有选股功能是否正常
- 权重优化功能是否正常
- 回测功能是否正常

---

## 六、注意事项

1. **首次运行**: 需要先执行一次预计算，否则前端显示空状态
2. **内存监控**: 建议在首次运行时监控内存使用情况
3. **日志观察**: 预计算日志输出到 `logs/optimizer.log`
4. **API 兼容**: 所有新增 API 独立，不影响现有功能

---

**开发完成，等待云汐测试验证。**