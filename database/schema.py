HR_SCHEMA = """
The HR database contains two governed data layers:

1. Current snapshot layer
- `employees`
- `employees_current`

2. Simulated historical trend layer
- `employees_monthly_history`
- `employees_trend_current`
- `workforce_monthly_events`
- `workforce_monthly_summary`

Important:
- `employees` and `employees_current` are the original IBM HR snapshot rows.
- The monthly trend tables are simulated from the base snapshot to support month-over-month and year-over-year analysis.
- When using the simulated history, clearly say the trend is simulated from the current workforce baseline rather than sourced from a real HRIS time-series feed.

TABLE: employees
Description:
  - One row per employee from the original IBM HR attrition CSV.
  - Use this for current snapshot headcount, attrition, compensation, tenure, satisfaction, promotion, and demographic analysis.

VIEW: employees_current
Description:
  - Compatibility view that mirrors `employees`.
  - Safe to use for current/latest workforce questions.

TABLE: employees_monthly_history
Description:
  - Simulated active employee monthly snapshots across a 36-month history.
  - One row per active employee per month.
  - Use this for simulated trend cuts by department, role, level, overtime, tenure, and promotion recency.

Important columns:
  - `SnapshotMonth`
  - `EmployeeNumber`
  - `SourceEmployeeNumber`
  - `SyntheticEmployee`
  - `IsLatestSnapshot`
  - `HireDate`
  - `HireThisMonth`
  - `PromotedThisMonth`
  - `Department`
  - `JobRole`
  - `JobLevel`
  - `MonthlyIncome`
  - `OverTime`
  - `YearsAtCompany`
  - `YearsInCurrentRole`
  - `YearsSinceLastPromotion`
  - `YearsWithCurrManager`
  - `TenureBand`

VIEW: employees_trend_current
Description:
  - Latest simulated active monthly snapshot only.
  - Use when you want the current simulated monthly roster without filtering `employees_monthly_history` yourself.

TABLE: workforce_monthly_events
Description:
  - Simulated monthly employee events.
  - Contains one row per hire, promotion, or exit event.

Important columns:
  - `SnapshotMonth`
  - `Department`
  - `JobRole`
  - `JobLevel`
  - `EventType`
  - `TenureAtEventYears`

TABLE: workforce_monthly_summary
Description:
  - Simulated monthly KPI summary table for both enterprise (`Department='All'`) and department-level rows.
  - Best table for month-over-month and year-over-year HR trend reporting.

Important columns:
  - `SnapshotMonth`
  - `Department`
  - `Headcount`
  - `HiresThisMonth`
  - `ExitsThisMonth`
  - `PromotionsThisMonth`
  - `NetChangeThisMonth`
  - `MonthlyHiringRatePct`
  - `MonthlyAttritionRatePct`
  - `MonthlyPromotionRatePct`
  - `Rolling12HiringRatePct`
  - `Rolling12AttritionRatePct`
  - `Rolling12PromotionRatePct`
  - `MoMHeadcountChange`
  - `MoMHeadcountChangePct`
  - `YoYHeadcountChange`
  - `YoYHeadcountChangePct`
  - `AverageYearsAtCompany`
  - `AverageYearsSinceLastPromotion`
  - `OverTimeSharePct`
  - `TenureBand0To1Pct`
  - `TenureBand2To4Pct`
  - `TenureBand5To9Pct`
  - `TenureBand10PlusPct`

Guidance:
  - Use `employees_current` or `employees` for current snapshot questions.
  - Use `workforce_monthly_summary` for month-over-month or year-over-year trend questions.
  - Use `employees_monthly_history` when the user wants a simulated historical cut by employee attributes.
  - Use `workforce_monthly_events` when the user specifically needs hires, promotions, or exits by month.
  - For trend analysis, explicitly label findings as simulated.

EXAMPLE QUERIES:
  -- Current headcount by department
  SELECT Department, COUNT(*) as HeadCount
  FROM employees_current
  GROUP BY Department
  ORDER BY HeadCount DESC;

  -- Simulated enterprise headcount trend with month-over-month and year-over-year change
  SELECT SnapshotMonth, Headcount, MoMHeadcountChangePct, YoYHeadcountChangePct
  FROM workforce_monthly_summary
  WHERE Department = 'All'
  ORDER BY SnapshotMonth;

  -- Simulated attrition trend by department
  SELECT SnapshotMonth, Department, Rolling12AttritionRatePct
  FROM workforce_monthly_summary
  WHERE Department != 'All'
  ORDER BY SnapshotMonth, Department;

  -- Simulated promotion trend by department
  SELECT SnapshotMonth, Department, Rolling12PromotionRatePct
  FROM workforce_monthly_summary
  WHERE Department != 'All'
  ORDER BY SnapshotMonth, Department;

  -- Simulated tenure mix trend
  SELECT SnapshotMonth, TenureBand0To1Pct, TenureBand2To4Pct, TenureBand5To9Pct, TenureBand10PlusPct
  FROM workforce_monthly_summary
  WHERE Department = 'All'
  ORDER BY SnapshotMonth;
"""
