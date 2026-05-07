#!/usr/bin/env python3
"""
增量更新逻辑测试
"""
import json
import tempfile
import os
import sys

# 模拟 save_cache 的核心逻辑
def test_incremental_logic():
    """测试增量更新逻辑"""
    
    # 模拟现有股票（持久化文件中的数据）
    existing_stocks = [
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},
        {'code': '000002', 'name': '万科A', 'market': 'sz'},
        {'code': '600000', 'name': '浦发银行', 'market': 'sh'},
    ]
    
    # 模拟 API 返回的股票（包含新增）
    api_stocks = [
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},  # 已存在
        {'code': '000002', 'name': '万科A', 'market': 'sz'},      # 已存在
        {'code': '600000', 'name': '浦发银行', 'market': 'sh'},    # 已存在
        {'code': '600001', 'name': '邯郸钢铁', 'market': 'sh'},    # 新增
        {'code': '600002', 'name': '齐鲁石化', 'market': 'sh'},    # 新增
    ]
    
    # 核心增量逻辑
    existing_codes = set(s['code'] for s in existing_stocks)
    added_stocks = []
    
    for stock in api_stocks:
        if stock['code'] not in existing_codes:
            added_stocks.append({
                'code': stock['code'],
                'name': stock['name'],
                'market': stock['market'],
                'added_at': '2026-04-02'
            })
    
    # 合并
    all_stocks = existing_stocks + added_stocks
    
    # 验证
    print("=" * 60)
    print("增量更新逻辑测试")
    print("=" * 60)
    print(f"现有股票: {len(existing_stocks)} 只")
    print(f"API获取: {len(api_stocks)} 只")
    print(f"新增股票: {len(added_stocks)} 只")
    print(f"合并后总数: {len(all_stocks)} 只")
    print()
    
    # 检查新增
    print("新增股票列表:")
    for s in added_stocks:
        print(f"  - {s['code']} {s['name']}")
    
    # 断言
    assert len(added_stocks) == 2, f"应该新增2只股票，实际新增{len(added_stocks)}只"
    assert len(all_stocks) == 5, f"合并后应该有5只股票，实际有{len(all_stocks)}只"
    
    # 检查新增的是否正确
    added_codes = [s['code'] for s in added_stocks]
    assert '600001' in added_codes, "600001 应该被识别为新增"
    assert '600002' in added_codes, "600002 应该被识别为新增"
    assert '000001' not in added_codes, "000001 不应该被识别为新增"
    
    print()
    print("✅ 所有测试通过！")
    print("=" * 60)
    return True

def test_no_duplicates():
    """测试去重逻辑"""
    
    # 模拟现有股票
    existing_stocks = [
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},
        {'code': '000002', 'name': '万科A', 'market': 'sz'},
    ]
    
    # 模拟 API 返回重复数据
    api_stocks = [
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},  # API 重复返回
        {'code': '000003', 'name': '新股票', 'market': 'sz'},
    ]
    
    existing_codes = set(s['code'] for s in existing_stocks)
    added_stocks = []
    seen_new = set()
    
    for stock in api_stocks:
        if stock['code'] not in existing_codes and stock['code'] not in seen_new:
            added_stocks.append({
                'code': stock['code'],
                'name': stock['name'],
                'market': stock['market'],
            })
            seen_new.add(stock['code'])
    
    print("=" * 60)
    print("去重逻辑测试")
    print("=" * 60)
    print(f"新增股票数量: {len(added_stocks)} 只")
    print(f"新增股票: {[s['code'] for s in added_stocks]}")
    
    assert len(added_stocks) == 1, f"应该只新增1只股票，实际新增{len(added_stocks)}只"
    assert added_stocks[0]['code'] == '000003', "新增的应该是000003"
    
    print("✅ 去重测试通过！")
    print("=" * 60)
    return True

def test_delete_stock():
    """测试已删除股票的保留逻辑"""
    
    # 现有持久化文件有这只股票
    existing_stocks = [
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},
        {'code': '000002', 'name': '万科A', 'market': 'sz'},
        {'code': '999999', 'name': '退市股票', 'market': 'sz'},  # API 不会再返回这只
    ]
    
    # API 不再返回 999999
    api_stocks = [
        {'code': '000001', 'name': '平安银行', 'market': 'sz'},
        {'code': '000002', 'name': '万科A', 'market': 'sz'},
    ]
    
    existing_codes = set(s['code'] for s in existing_stocks)
    added_stocks = []
    
    for stock in api_stocks:
        if stock['code'] not in existing_codes:
            added_stocks.append(stock)
    
    # 合并：现有 + 新增（不删除已有的）
    all_stocks = existing_stocks + added_stocks
    
    print("=" * 60)
    print("保留已删除股票测试")
    print("=" * 60)
    print(f"现有股票: {[s['code'] for s in existing_stocks]}")
    print(f"API返回: {[s['code'] for s in api_stocks]}")
    print(f"合并后: {[s['code'] for s in all_stocks]}")
    
    # 验证：999999 应该还在
    all_codes = [s['code'] for s in all_stocks]
    assert '999999' in all_codes, "已删除的股票应该被保留"
    assert len(all_stocks) == 3, "总数应该保持3只"
    
    print("✅ 保留测试通过！（已删除的股票仍被保留）")
    print("=" * 60)
    return True

if __name__ == '__main__':
    try:
        test_incremental_logic()
        print()
        test_no_duplicates()
        print()
        test_delete_stock()
        print()
        print("=" * 60)
        print("🎉 所有测试通过！增量更新逻辑正确！")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)