# 修复记录：今日推荐应该用凌晨预计算正式结果

## 问题发现
用户反馈今日推荐股票和凌晨定时任务跑出来的结果不一样。

## 问题根因
`portfolio_tracking.html` 页面的"今日推荐"区块调用了错误的API：
- 错误API: `/api/precompute/optimization-result-test`（测试版）
- 正确API: `/api/precompute/optimization-result`（正式版）

测试版API读取的是 `optimization_result_test.json`（测试版数据），而不是凌晨定时任务生成的 `optimization_result.json`（正式版数据）。

## 修复方案
修改 `portfolio_tracking.html` 页面的 `loadTodayRecommendations()` 函数，将API调用改为正式版。

### 修复代码位置
文件: `templates/portfolio_tracking.html`
行号: 1073

### 修复前
```javascript
async function loadTodayRecommendations() {
    console.log('[Recommendations] 加载今日推荐');
    
    try {
        const response = await fetch('/api/precompute/optimization-result-test');  // 错误：测试版
        const result = await response.json();
        ...
    }
}
```

### 修复后
```javascript
async function loadTodayRecommendations() {
    console.log('[Recommendations] 加载今日推荐');
    
    try {
        // 【修复】使用正式版API，读取凌晨定时任务生成的正式结果
        const response = await fetch('/api/precompute/optimization-result');  // 正确：正式版
        const result = await response.json();
        ...
    }
}
```

## 验证结果
修复后，今日推荐区块将显示凌晨定时任务的正式结果：

| 排名 | 代码 | 名称 | 得分 |
|------|------|------|------|
| 1 | 600182 | - | 98.94 |
| 2 | 001965 | 招商公路 | 97.37 |
| 3 | 000037 | 深南电A | 96.94 |
| 4 | 001367 | 海森药业 | 96.27 |
| 5 | 002202 | 金风科技 | 95.40 |

数据来源: `optimization_result.json`
更新时间: 2026-04-16 05:44:48

## 其他页面检查
- `stock_scoring.html` 页面的今日推荐区块已使用正式版API，无需修复
- `stock_scoring.html` 的测试版API调用（`loadPrecomputeTestResult()`）仅用于加载净值曲线，不影响今日推荐显示

## 修复完成时间
2026-04-16 12:50

---

修复人: 云舟 🛠️