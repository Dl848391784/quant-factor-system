# data_fetchers 模块规范

> 本文档定义 data_fetchers/ 目录下数据拉取脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v0.1（骨架版，待补充）

---

## 概述

data_fetchers 模块负责从外部数据源拉取因子数据、收益数据等，存储到 cache 目录。

**模块定位：**
- 输入：外部数据源（API、数据库等）
- 输出：cache/factor_data/ 缓存文件

---

## 数据流程

```
外部数据源 → data_fetchers/ → cache/factor_data/ → factor_ic/
```

**关键原则：**
- factor_ic 不自行拉取数据，只使用 cache
- data_fetchers 负责数据质量和格式转换

---

## 缓存格式

待定义：

- factor_data.json.gz 结构
- return_data.json.gz 结构
- 元数据字段（dates、period、metadata）

---

## 拉取脚本规范

待定义：

- 脚本命名格式
- 数据源配置
- 增量更新策略
- 错误处理

---

## 待补充内容

```
□ 缓存文件格式规范
□ 数据源定义
□ 增量更新规则
□ 错误处理规范
□ 数据质量检查
```

---

*最后更新: 2026-05-19*