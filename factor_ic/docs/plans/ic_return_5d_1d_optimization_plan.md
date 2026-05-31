# ic_return_5d_1d.py 优化计划

> 创建时间: 2026-05-31 17:30 (北京时间)
> 执行模式: 分步执行（遵循 Bite-sized Tasks 原则）
> 参考技能: superpowers-workflow + karpathy-guidelines

---

## 诊断结论

**诊断方法**：对照 superpowers-workflow Spec Compliance 检查清单 + PROJECT.md 规范

**发现问题**：
1. **流程文档不完整**（规范遗漏）- 运行结果缺失实测数据
2. **MODULE.md 版本历史缺失**（规范遗漏）- 未同步新增因子记录
3. **流程文档标题格式不规范**（规范遗漏）- 与命名规范不一致
4. **测试用例缺少 .md 文档格式**（规范遗漏）- 其他因子都有两种格式

---

## 优化方案（分步执行）

### Round 1: 流程文档完整性修复（优先级：高）

**Step 1: 运行脚本获取实测数据**
- 任务：执行 `python3 factor_ic/ic_return_5d_1d.py --force-full`
- 验证：检查输出文件 `ic_return_5d_1d_analysis_result.json`
- 产出：真实 IC 指标数据（ic_mean, ic_std, ICIR, p_value, valid_days）

**Step 2: 流程文档标题格式修正**
- 文件：`factor_ic/docs/ic_return_5d_1d_flow.md`
- 修改：标题从 `Return_5d_1D` 改为 `ic_return_5d_1d`（遵循命名规范）
- 验证：grep 检查标题行

**Step 3: 流程文档实测数据补充**
- 文件：`factor_ic/docs/ic_return_5d_1d_flow.md`
- 修改：第47-58行"待实测"替换为真实数据
- 同步更新：五维度判断结论
- 验证：对照实际输出 JSON 的字段值
- 时间标注：更新"生成时间"为实测完成时间

### Round 2: MODULE.md 版本历史同步（优先级：高）

**Step 4: MODULE.md 新增版本记录**
- 文件：`factor_ic/MODULE.md`
- 修改：版本历史章节新增 v3.17 条目
- 内容：
  ```
  19. v3.17（2026-05-31）：
      - 新增 ic_return_5d_1d.py 因子脚本
      - 新增流程文档 ic_return_5d_1d_flow.md
      - 新增测试用例 test_ic_return_5d_1d.py
      - 因子定义：Return_5d = close[t] / close[t-5] - 1（5日累计涨跌幅）
  ```
- 验证：grep 检查版本历史

### Round 3: 测试用例文档格式补充（优先级：中）

**Step 5: 创建测试用例 .md 文档**
- 文件：`factor_ic/test_cases/ic_return_5d_1d_test_cases.md`（新建）
- 内容：参考其他因子测试用例格式（如 ic_rsi_1d_test_cases.md）
- 章节：
  - 测试覆盖矩阵
  - 测试场景说明
  - 验证检查清单
- 验证：文件存在 + 格式符合规范

### Round 4: 代码质量审查（优先级：中）

**Step 6: 代码脚本 Spec Compliance 检查**
- 对照 MODULE.md 检查清单逐项核对：
  - 输出结构合规（字段完整性）
  - 公共模块复用（run_complex_factor_ic）
  - 异常处理规范（RuntimeError vs Exception）
  - 日志规范（logger.info/error/exception）
  - 参数类型约定（Path | str）
- 验证：pytest 测试通过

---

## 执行顺序

```
Step 1（运行脚本）→ Step 2（标题修正）→ Step 3（数据补充）
    ↓
Step 4（MODULE.md同步）
    ↓
Step 5（测试文档补充）
    ↓
Step 6（代码审查）→ pytest 验证 → Git commit
```

---

## 验证检查清单

**完成后必须验证：**
- [ ] 流程文档实测数据完整（ic_mean, ICIR, valid_days 等有真实值）
- [ ] 流程文档标题格式合规（`ic_return_5d_1d`）
- [ ] 流程文档时间标注更新（实测完成时间）
- [ ] MODULE.md 版本历史包含 v3.17
- [ ] 测试用例 .md 文档存在
- [ ] pytest 测试全部通过
- [ ] Git commit 已提交（commit 不 push）

---

## Git 提交规划

**提交时机**：所有步骤完成后统一提交

**提交格式**：
```
docs(factor_ic): ic_return_5d_1d 完整性优化

- 流程文档实测数据补充（替换"待实测"）
- 流程文档标题格式修正（遵循命名规范）
- MODULE.md 版本历史同步（新增 v3.17）
- 新增测试用例 .md 文档格式
- 时间标注同步更新

遵循 superpowers-workflow 4阶段流程
```

---

## 参考规范

- PROJECT.md：输出数据规范、命名规范
- MODULE.md：因子脚本规范、版本历史格式
- superpowers-workflow：Spec Compliance 检查清单
- karpathy-guidelines：Comment Accuracy（注释必须匹配实际）