# Factor IC Output Format Comparison Table

## Overview

This document describes the output format of each factor IC analysis script in the `factor_ic` directory.

Project Path: `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/factor_ic/`

---

## Output Format Comparison Table

| Script | Output File | Storage Path | Output Format | Main Fields |
|--------|-------------|--------------|---------------|-------------|
| rsi_ic.py | rsi_ic_data.json | Project root (`factor_ic_analyzer/`) | JSON | ic_mean, ic_std, icir, ic_series(dates, ic_values, rolling_ic_mean), positive_ratio, t_stat, significance, n_days, n_assets, summary |
| kdj_j_factor.py | kdj_j_analysis_result.json | factor_ic/ | JSON | success, ic_metrics, ic_series, layered_result, factor_stats, params, generated_at |
| bollinger_pb_factor.py | bollinger_pb_analysis_result.json | factor_ic/ | JSON | success, ic_metrics, ic_series, layered_result, factor_stats, params, generated_at |
| turnover_surge_factor.py | (Returns dict, no file save) | N/A | Dict | success, ic_metrics, ic_series, layered_result, filter_stats, params, generated_at |
| main_inflow_ratio_factor.py | (Returns dict, no file save) | N/A | Dict | success, ic_metrics, ic_series, layered_result, factor_stats, params, generated_at |
| precompute_volume_ratio.py | volume_ratio_analysis_result.json | factor_ic/ | JSON | ic_metrics, ic_series, layered_result, params, generated_at |

---

## Detailed Field Structure

### 1. rsi_ic.py

**Output File**: `rsi_ic_data.json`

**Storage Path**: `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/rsi_ic_data.json`

**Output Fields**:
```json
{
  "dates": ["2025-01-01", "2025-01-02", ...],           // Date list
  "ic_values": [0.05, -0.03, ...],                      // Daily IC values
  "rolling_ic_mean": [0.04, 0.03, ...],                 // 20-day rolling IC mean
  "ic_mean": 0.0325,                                    // IC mean
  "ic_std": 0.15,                                       // IC standard deviation
  "icir": 0.22,                                         // ICIR (IC mean / IC std)
  "positive_ratio": 0.55,                               // Positive IC ratio
  "t_stat": 2.5,                                        // t-statistic
  "significance": "**",                                 // Significance level (*, **, ***)
  "n_days": 250,                                        // Number of trading days
  "n_assets": 100,                                      // Number of assets
  "summary": "IC均值=0.0325, ICIR=0.22, ..."           // Summary text
}
```

**Note**: Only IC analysis, no layered backtest results.

---

### 2. kdj_j_factor.py

**Output File**: `kdj_j_analysis_result.json`

**Storage Path**: `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/factor_ic/kdj_j_analysis_result.json`

**Output Fields**:
```json
{
  "success": true,
  "ic_metrics": {
    "ic_mean": 0.0325,
    "ic_std": 0.15,
    "icir": 0.22,
    "t_stat": 2.5,
    "p_value": 0.05,
    "positive_ratio": 0.55,
    "n_days": 250,
    "n_assets": 100,
    "significance": "**",
    "summary": "IC均值=0.0325, ICIR=0.22, ..."
  },
  "ic_series": {
    "dates": ["2025-01-01", ...],
    "ic_values": [0.05, ...],
    "rolling_ic_mean": [0.04, ...]
  },
  "layered_result": {
    "layer_returns": [...],
    "cumulative_returns": [...],
    "statistics": [...],
    "long_short": [...],
    "num_layers": 5,
    "n_days": 250,
    "n_stocks": 100,
    "summary": {
      "long_short_annual_return": 0.15,
      "long_short_sharpe": 1.2,
      "long_short_max_drawdown": -0.08,
      "monotonicity_passed": true
    }
  },
  "factor_stats": {
    "total_records": 25000,
    "valid_records": 24000,
    "missing_price_count": 1000,
    "n": 9,
    "m1": 3,
    "m2": 3
  },
  "params": {
    "n_days": 500,
    "n": 9,
    "m1": 3,
    "m2": 3,
    "num_layers": 5,
    "factor_col": "kdj_j"
  },
  "generated_at": "2026-04-07T10:30:00"
}
```

---

### 3. bollinger_pb_factor.py

**Output File**: `bollinger_pb_analysis_result.json`

**Storage Path**: `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/factor_ic/bollinger_pb_analysis_result.json`

**Output Fields**:
```json
{
  "success": true,
  "ic_metrics": {
    "ic_mean": 0.0325,
    "ic_std": 0.15,
    "icir": 0.22,
    "t_stat": 2.5,
    "p_value": 0.05,
    "positive_ratio": 0.55,
    "n_days": 250,
    "n_assets": 100,
    "significance": "**",
    "summary": "IC均值=0.0325, ICIR=0.22, ..."
  },
  "ic_series": {
    "dates": ["2025-01-01", ...],
    "ic_values": [0.05, ...],
    "rolling_ic_mean": [0.04, ...]
  },
  "layered_result": {
    "layer_returns": [...],
    "cumulative_returns": [...],
    "statistics": [...],
    "long_short": [...],
    "num_layers": 5,
    "n_days": 250,
    "n_stocks": 100,
    "summary": {...}
  },
  "factor_stats": {
    "total_records": 25000,
    "valid_records": 24000,
    "missing_price_count": 1000,
    "n": 20,
    "k": 2.0
  },
  "params": {
    "n_days": 500,
    "n": 20,
    "k": 2.0,
    "num_layers": 5,
    "factor_col": "bollinger_pb"
  },
  "generated_at": "2026-04-07T10:30:00"
}
```

---

### 4. turnover_surge_factor.py

**Output File**: None (Returns Python dict directly)

**Storage Path**: N/A (No file saved)

**Output Fields** (Returned dict):
```json
{
  "success": true,
  "ic_metrics": {
    "ic_mean": 0.0325,
    "ic_std": 0.15,
    "icir": 0.22,
    "t_stat": 2.5,
    "p_value": 0.05,
    "positive_ratio": 0.55,
    "n_days": 250,
    "n_assets": 100,
    "significance": "**",
    "summary": "IC均值=0.0325, ICIR=0.22, ..."
  },
  "ic_series": {
    "dates": ["2025-01-01", ...],
    "ic_values": [0.05, ...],
    "rolling_ic_mean": [0.04, ...]
  },
  "layered_result": {
    "layer_returns": [...],
    "cumulative_returns": [...],
    "statistics": [...],
    "long_short": [...],
    "num_layers": 5,
    "n_days": 250,
    "n_stocks": 100,
    "summary": {...}
  },
  "filter_stats": {
    "total_records": 25000,
    "turnover_surge_count": 5000,
    "price_up_count": 10000,
    "both_conditions_count": 3000,
    "filtered_count": 3000,
    "filter_ratio": 0.12
  },
  "params": {
    "n_days": 500,
    "max_stocks": 0,
    "num_layers": 5,
    "factor_col": "turnover_surge",
    "filter_conditions": true
  },
  "generated_at": "2026-04-08T10:30:00"
}
```

---

### 5. main_inflow_ratio_factor.py

**Output File**: None (Returns Python dict directly)

**Storage Path**: N/A (No file saved)

**Output Fields** (Returned dict):
```json
{
  "success": true,
  "ic_metrics": {
    "ic_mean": 0.0325,
    "ic_std": 0.15,
    "icir": 0.22,
    "t_stat": 2.5,
    "p_value": 0.05,
    "positive_ratio": 0.55,
    "n_days": 250,
    "n_assets": 100,
    "significance": "**",
    "summary": "IC均值=0.0325, ICIR=0.22, ..."
  },
  "ic_series": {
    "dates": ["2025-01-01", ...],
    "ic_values": [0.05, ...],
    "rolling_ic_mean": [0.04, ...]
  },
  "layered_result": {
    "layer_returns": [...],
    "cumulative_returns": [...],
    "statistics": [...],
    "long_short": [...],
    "num_layers": 10,
    "n_days": 250,
    "n_stocks": 100,
    "summary": {...}
  },
  "factor_stats": {
    "total_records": 25000,
    "valid_records": 24000,
    "zero_cap_count": 500,
    "missing_inflow_count": 1000,
    "winsorized_count": 200
  },
  "params": {
    "n_days": 500,
    "max_stocks": 0,
    "num_layers": 10,
    "factor_col": "main_inflow_ratio",
    "winsorize": true
  },
  "generated_at": "2026-04-06T10:30:00"
}
```

---

### 6. precompute_volume_ratio.py

**Output File**: `volume_ratio_analysis_result.json`

**Storage Path**: `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/factor_ic/volume_ratio_analysis_result.json`

**Output Fields**:
```json
{
  "ic_metrics": {
    "ic_mean": 0.0325,
    "ic_std": 0.15,
    "icir": 0.22,
    "t_stat": 2.5,
    "p_value": 0.05,
    "positive_ratio": 0.55,
    "n_days": 250,
    "n_assets": 100,
    "significance": "**",
    "summary": "IC均值=0.0325, ICIR=0.22, ..."
  },
  "ic_series": {
    "dates": ["2025-01-01", ...],
    "ic_values": [0.05, ...],
    "rolling_ic_mean": [0.04, ...]
  },
  "layered_result": {
    "layer_returns": [...],
    "cumulative_returns": [...],
    "statistics": [...],
    "long_short": [...],
    "num_layers": 5,
    "n_days": 250,
    "n_stocks": 100,
    "summary": {
      "long_short_annual_return": 0.15,
      "long_short_sharpe": 1.2,
      "long_short_max_drawdown": -0.08,
      "monotonicity_passed": true
    }
  },
  "params": {
    "n_days": 500,
    "max_stocks": 0,
    "num_layers": 5,
    "factor_col": "volume_ratio_5"
  },
  "generated_at": "2026-04-07T03:30:00"
}
```

---

## Field Summary

### Common IC Metrics Fields
| Field | Description |
|-------|-------------|
| ic_mean | Mean of daily IC values |
| ic_std | Standard deviation of IC values |
| icir | ICIR = ic_mean / ic_std |
| t_stat | t-statistic for IC significance |
| p_value | p-value for t-test |
| positive_ratio | Ratio of positive IC days |
| n_days | Number of trading days analyzed |
| n_assets | Number of assets/stocks |
| significance | Significance level (*, **, ***) |
| summary | Text summary of IC results |

### IC Series Fields
| Field | Description |
|-------|-------------|
| dates | List of trading dates |
| ic_values | List of daily IC values |
| rolling_ic_mean | 20-day rolling mean of IC |

### Layered Backtest Fields
| Field | Description |
|-------|-------------|
| layer_returns | Daily returns for each layer |
| cumulative_returns | Cumulative returns for each layer |
| statistics | Layer statistics (annual_return, sharpe, etc.) |
| long_short | Long-short portfolio performance |
| num_layers | Number of layers (default 5 or 10) |
| n_days | Number of trading days in backtest |
| n_stocks | Number of stocks in backtest |
| summary.long_short_annual_return | Annual return of long-short portfolio |
| summary.long_short_sharpe | Sharpe ratio of long-short portfolio |
| summary.long_short_max_drawdown | Max drawdown of long-short portfolio |
| summary.monotonicity_passed | Monotonicity test result |

### Factor-specific Stats Fields
| Script | Factor Stats Fields |
|--------|---------------------|
| kdj_j_factor.py | total_records, valid_records, missing_price_count, n, m1, m2 |
| bollinger_pb_factor.py | total_records, valid_records, missing_price_count, n, k |
| turnover_surge_factor.py | total_records, turnover_surge_count, price_up_count, both_conditions_count, filtered_count, filter_ratio |
| main_inflow_ratio_factor.py | total_records, valid_records, zero_cap_count, missing_inflow_count, winsorized_count |

---

## Key Differences

1. **File Saving**: 
   - `rsi_ic.py`, `kdj_j_factor.py`, `bollinger_pb_factor.py`, `precompute_volume_ratio.py` save results to JSON files
   - `turnover_surge_factor.py`, `main_inflow_ratio_factor.py` only return Python dict (no file save in __main__)

2. **Layered Backtest**:
   - All scripts except `rsi_ic.py` include layered backtest results
   - `rsi_ic.py` only outputs IC analysis results

3. **Factor Stats**:
   - Each factor has its own specific factor_stats fields based on factor calculation logic

4. **Success Field**:
   - `kdj_j_factor.py`, `bollinger_pb_factor.py`, `turnover_surge_factor.py`, `main_inflow_ratio_factor.py` include `success` field
   - `rsi_ic.py`, `precompute_volume_ratio.py` do not include `success` field

---

## File Storage Locations

| Script | Storage Location |
|--------|------------------|
| rsi_ic.py | `{project_root}/rsi_ic_data.json` |
| kdj_j_factor.py | `{factor_ic}/kdj_j_analysis_result.json` |
| bollinger_pb_factor.py | `{factor_ic}/bollinger_pb_analysis_result.json` |
| turnover_surge_factor.py | N/A (no file) |
| main_inflow_ratio_factor.py | N/A (no file) |
| precompute_volume_ratio.py | `{factor_ic}/volume_ratio_analysis_result.json` |

Where:
- `{project_root}` = `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/`
- `{factor_ic}` = `/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/factor_ic/`

---

Generated: 2026-05-07