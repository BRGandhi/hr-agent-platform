# Data Dictionary — IBM HR Attrition Dataset

The platform uses the **IBM HR Analytics Employee Attrition & Performance** dataset.
Source: [Kaggle](https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset)

- **Rows:** 1,470 employees
- **Columns:** 35
- **SQLite table:** `employees`

---

## Column Reference

| Column | Type | Range / Values | Description |
|---|---|---|---|
| `Age` | Integer | 18–60 | Employee age in years |
| `Attrition` | Text | `Yes` / `No` | Whether the employee left (**target variable**) |
| `BusinessTravel` | Text | `Non-Travel`, `Travel_Rarely`, `Travel_Frequently` | Travel frequency |
| `DailyRate` | Integer | 102–1,499 | Daily pay rate in dollars |
| `Department` | Text | `Human Resources`, `Research & Development`, `Sales` | Department name |
| `DistanceFromHome` | Integer | 1–29 | Miles from office |
| `Education` | Integer | 1–5 | Education level (1=Below College, 2=College, 3=Bachelor, 4=Master, 5=Doctor) |
| `EducationField` | Text | `Life Sciences`, `Medical`, `Marketing`, `Technical Degree`, `Human Resources`, `Other` | Field of study |
| `EmployeeCount` | Integer | 1 (constant) | Always 1 — not analytically useful |
| `EmployeeNumber` | Integer | 1–2068 | Unique employee ID |
| `EnvironmentSatisfaction` | Integer | 1–4 | Satisfaction with work environment (1=Low, 2=Medium, 3=High, 4=Very High) |
| `Gender` | Text | `Male` / `Female` | Gender |
| `HourlyRate` | Integer | 30–100 | Hourly pay rate |
| `JobInvolvement` | Integer | 1–4 | Level of job involvement (1=Low, 4=Very High) |
| `JobLevel` | Integer | 1–5 | Job hierarchy level (1=Entry, 5=Senior Executive) |
| `JobRole` | Text | 9 values (see below) | Job title |
| `JobSatisfaction` | Integer | 1–4 | Job satisfaction rating (1=Low, 4=Very High) |
| `MaritalStatus` | Text | `Single`, `Married`, `Divorced` | Marital status |
| `MonthlyIncome` | Integer | 1,009–19,999 | Monthly gross income in dollars |
| `MonthlyRate` | Integer | 2,094–26,999 | Monthly rate (different from MonthlyIncome) |
| `NumCompaniesWorked` | Integer | 0–9 | Previous employers count |
| `Over18` | Text | `Y` (constant) | Always Y — not analytically useful |
| `OverTime` | Text | `Yes` / `No` | Whether employee works overtime |
| `PercentSalaryHike` | Integer | 11–25 | Last salary increase percentage |
| `PerformanceRating` | Integer | 1–4 | Performance rating (3=Excellent, 4=Outstanding; no 1 or 2 in dataset) |
| `RelationshipSatisfaction` | Integer | 1–4 | Satisfaction with workplace relationships |
| `StandardHours` | Integer | 80 (constant) | Always 80 — not analytically useful |
| `StockOptionLevel` | Integer | 0–3 | Stock option grant level |
| `TotalWorkingYears` | Integer | 0–40 | Total years in workforce |
| `TrainingTimesLastYear` | Integer | 0–6 | Training sessions attended last year |
| `WorkLifeBalance` | Integer | 1–4 | Work-life balance rating (1=Bad, 4=Best) |
| `YearsAtCompany` | Integer | 0–40 | Tenure at current company |
| `YearsInCurrentRole` | Integer | 0–18 | Years in current role |
| `YearsSinceLastPromotion` | Integer | 0–15 | Years since last promotion |
| `YearsWithCurrManager` | Integer | 0–17 | Years with current manager |

---

## JobRole Values
- `Healthcare Representative`
- `Human Resources`
- `Laboratory Technician`
- `Manager`
- `Manufacturing Director`
- `Research Director`
- `Research Scientist`
- `Sales Executive`
- `Sales Representative`

---

## Key Findings in the Dataset (baseline)

| Metric | Value |
|---|---|
| Overall attrition rate | 16.1% (237 of 1,470) |
| Highest attrition department | Sales (21%) |
| Highest attrition role | Sales Representative (~40%) |
| Overtime workers attrition | ~31% vs ~10% non-OT |
| Single employees attrition | ~26% vs ~12% married |
| Low job satisfaction (1) attrition | ~23% |
| Low environment satisfaction (1) attrition | ~25% |
| Frequent travelers attrition | ~25% |
| Income <$3K/month attrition | ~26% |

---

## Constant Columns (exclude from analysis)
These columns have no variance and should be excluded from statistical analysis:
- `EmployeeCount` — always 1
- `Over18` — always "Y"
- `StandardHours` — always 80

---

## Notes for Customization
- **Attrition column:** The agent and all pre-built queries assume `Attrition` contains `'Yes'` or `'No'` strings. If your data uses `1`/`0` or `true`/`false`, update the SQL in `agent/tool_executor.py` and `database/schema.py`.
- **MonthlyIncome vs DailyRate vs HourlyRate:** Three separate pay metrics exist. MonthlyIncome is the most commonly used for compensation analysis.
- **Satisfaction scales:** All satisfaction metrics (Job, Environment, Relationship, WorkLifeBalance) use 1–4 scales where 1=lowest. Treat as ordinal, not continuous, for strict statistical work.
