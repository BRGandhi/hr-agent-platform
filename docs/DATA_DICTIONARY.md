# Data Dictionary

This document describes the data model used by the HR Insights Platform. The repo currently uses three SQLite databases:
- `hr_data.db`
- `access_control.db`
- `context_store.db`

Together, they provide:
- workforce analytics data
- authorization and scoping data
- memory and contextual reference data

Latest release context:
- this dictionary includes the simulated monthly workforce history, trend-summary views, and derived trend-tag behavior introduced in the April 16, 2026 release wave documented in [RELEASE_NOTES_2026-04-16.md](RELEASE_NOTES_2026-04-16.md)

## 1. Logical Data Model

### 1.1 `hr_data.db`
Primary analytics database containing:
- current snapshot tables: `employees`, `employees_current`
- simulated trend tables: `employees_monthly_history`, `employees_trend_current`, `workforce_monthly_events`, `workforce_monthly_summary`, `workforce_trend_latest_summary`

### 1.2 `access_control.db`
Authorization database mapping signed-in users to role and scope.

### 1.3 `context_store.db`
Memory and context database containing:
- recent conversation history
- saved insight summaries for recall
- feedback on saved responses
- HR policy and schema documents

## 2. `hr_data.db`

The platform uses the IBM HR Analytics Employee Attrition & Performance dataset as the current demo workforce dataset.

Source:
- https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset

Expected runtime tables:
- `employees`
- `employees_current`
- `employees_monthly_history`
- `employees_trend_current`
- `workforce_monthly_events`
- `workforce_monthly_summary`
- `workforce_trend_latest_summary`

### 2.1 Row and column counts

Current snapshot layer:
- `employees`: 1,470 rows, 35 columns
- `employees_current`: compatibility view over `employees`

Simulated trend layer:
- `employees_monthly_history`: 42,097 rows
- `employees_trend_current`: 1,233 rows in the latest simulated snapshot
- `workforce_monthly_events`: 2,550 rows
- `workforce_monthly_summary`: 144 rows
- `workforce_trend_latest_summary`: 4 rows in the latest simulated summary view

### 2.2 Column reference

| Column | Type | Description |
|---|---|---|
| `Age` | Integer | Employee age in years |
| `Attrition` | Text | `Yes` or `No` |
| `BusinessTravel` | Text | Travel frequency |
| `DailyRate` | Integer | Daily compensation rate |
| `Department` | Text | Department name |
| `DistanceFromHome` | Integer | Distance from office |
| `Education` | Integer | Education level code |
| `EducationField` | Text | Field of study |
| `EmployeeCount` | Integer | Constant field, analytically unhelpful |
| `EmployeeNumber` | Integer | Unique employee identifier |
| `EnvironmentSatisfaction` | Integer | Satisfaction score |
| `Gender` | Text | Gender |
| `HourlyRate` | Integer | Hourly rate |
| `JobInvolvement` | Integer | Job involvement score |
| `JobLevel` | Integer | Hierarchy level |
| `JobRole` | Text | Job role |
| `JobSatisfaction` | Integer | Job satisfaction score |
| `MaritalStatus` | Text | Marital status |
| `MonthlyIncome` | Integer | Monthly income |
| `MonthlyRate` | Integer | Monthly rate |
| `NumCompaniesWorked` | Integer | Number of prior employers |
| `Over18` | Text | Constant field |
| `OverTime` | Text | Whether employee works overtime |
| `PercentSalaryHike` | Integer | Latest salary hike percentage |
| `PerformanceRating` | Integer | Performance score |
| `RelationshipSatisfaction` | Integer | Relationship satisfaction score |
| `StandardHours` | Integer | Constant field |
| `StockOptionLevel` | Integer | Stock option level |
| `TotalWorkingYears` | Integer | Total years worked |
| `TrainingTimesLastYear` | Integer | Training sessions last year |
| `WorkLifeBalance` | Integer | Work-life balance score |
| `YearsAtCompany` | Integer | Tenure at current company |
| `YearsInCurrentRole` | Integer | Years in current role |
| `YearsSinceLastPromotion` | Integer | Years since last promotion |
| `YearsWithCurrManager` | Integer | Years with current manager |

### 2.3 Important semantic notes
- `Attrition='Yes'` means the employee is counted as having left.
- `EmployeeNumber` is the only stable employee-level identifier in the demo dataset.
- The dataset does not include real employee names.
- Standard reports therefore use employee labels derived from `EmployeeNumber`.
- The monthly trend tables are simulated from the base snapshot and should be described as simulated when used in analysis.

### 2.4 Simulated monthly roster table: `employees_monthly_history`

Purpose:
- one row per active employee per simulated month
- supports filtered trend work by department, role, level, overtime, tenure, and promotion recency
- acts as the detailed source for filtered trend charts when the user asks for a narrower cut than the aggregate summary table can provide

Important columns:

| Column | Type | Description |
|---|---|---|
| `SnapshotMonth` | Text | First day of the simulated month in `YYYY-MM-DD` format |
| `SnapshotYear` | Integer | Numeric calendar year |
| `SnapshotMonthNumber` | Integer | Numeric month |
| `SnapshotQuarter` | Integer | Quarter of year |
| `EmployeeNumber` | Integer | Simulated employee identifier present in that month |
| `SourceEmployeeNumber` | Integer | Base-snapshot employee used as the modeling anchor |
| `SyntheticEmployee` | Integer | `1` when the employee was synthetically created during simulation |
| `IsLatestSnapshot` | Integer | `1` for the latest simulated month |
| `HireDate` | Text | Simulated hire date |
| `HireThisMonth` | Integer | `1` if the employee was hired in that month |
| `PromotedThisMonth` | Integer | `1` if the employee was promoted in that month |
| `Department` | Text | Department in that month |
| `JobRole` | Text | Job role in that month |
| `JobLevel` | Integer | Job level in that month |
| `MonthlyIncome` | Real | Simulated monthly income |
| `OverTime` | Text | `Yes` or `No` |
| `YearsAtCompany` | Real | Simulated tenure at company in years |
| `YearsInCurrentRole` | Real | Simulated tenure in current role in years |
| `YearsSinceLastPromotion` | Real | Simulated years since last promotion |
| `YearsWithCurrManager` | Real | Simulated years with current manager |
| `TenureBand` | Text | Derived tenure band: `0-1`, `2-4`, `5-9`, or `10+` |

### 2.5 Simulated monthly event table: `workforce_monthly_events`

Purpose:
- one row per hire, exit, or promotion event
- supports event-level monthly analysis when the question is specifically about workforce movement rather than roster state

Important columns:

| Column | Type | Description |
|---|---|---|
| `SnapshotMonth` | Text | Month in which the event occurred |
| `SnapshotYear` | Integer | Calendar year |
| `SnapshotMonthNumber` | Integer | Calendar month |
| `EmployeeNumber` | Integer | Employee tied to the event |
| `SourceEmployeeNumber` | Integer | Base employee anchor |
| `SyntheticEmployee` | Integer | Indicates whether the employee is synthetic |
| `Department` | Text | Department at time of event |
| `JobRole` | Text | Role at time of event |
| `JobLevel` | Integer | Level at time of event |
| `EventType` | Text | `hire`, `exit`, or `promotion` |
| `TenureAtEventYears` | Real | Tenure at time of event |
| `YearsSinceLastPromotion` | Real | Simulated years since prior promotion |
| `MonthlyIncome` | Real | Monthly income at event time |
| `OverTime` | Text | Overtime flag at event time |

### 2.6 Simulated monthly summary table: `workforce_monthly_summary`

Purpose:
- monthly KPI summary for both enterprise (`Department='All'`) and department rows
- main source for MoM, YoY, rolling-12, and tenure-mix trend reporting

Important columns:

| Column | Type | Description |
|---|---|---|
| `SnapshotMonth` | Text | Month represented by the row |
| `Department` | Text | `All` for enterprise or a department name |
| `Headcount` | Integer | End-of-month headcount |
| `StartOfMonthHeadcount` | Integer | Start-of-month headcount |
| `HiresThisMonth` | Integer | Monthly hire count |
| `ExitsThisMonth` | Integer | Monthly exit count |
| `PromotionsThisMonth` | Integer | Monthly promotion count |
| `NetChangeThisMonth` | Integer | Hires minus exits |
| `MonthlyHiringRatePct` | Real | Hires as a share of start-of-month headcount |
| `MonthlyAttritionRatePct` | Real | Exits as a share of start-of-month headcount |
| `MonthlyPromotionRatePct` | Real | Promotions as a share of start-of-month headcount |
| `AverageYearsAtCompany` | Real | Average simulated tenure |
| `AverageYearsSinceLastPromotion` | Real | Average simulated years since last promotion |
| `AverageMonthlyIncome` | Real | Average simulated monthly income |
| `OverTimeSharePct` | Real | Share of employees marked overtime |
| `TenureBand0To1Pct` | Real | Share of employees in `0-1` years at company |
| `TenureBand2To4Pct` | Real | Share of employees in `2-4` years at company |
| `TenureBand5To9Pct` | Real | Share of employees in `5-9` years at company |
| `TenureBand10PlusPct` | Real | Share of employees in `10+` years at company |
| `MoMHeadcountChange` | Integer | Numeric month-over-month headcount delta |
| `MoMHeadcountChangePct` | Real | Percentage month-over-month headcount delta |
| `Rolling12Hires` | Integer | Rolling 12-month hires |
| `Rolling12Exits` | Integer | Rolling 12-month exits |
| `Rolling12Promotions` | Integer | Rolling 12-month promotions |
| `Rolling12HiringRatePct` | Real | Rolling 12-month hiring rate |
| `Rolling12AttritionRatePct` | Real | Rolling 12-month attrition rate |
| `Rolling12PromotionRatePct` | Real | Rolling 12-month promotion rate |
| `YoYHeadcountChange` | Integer | Numeric year-over-year headcount delta |
| `YoYHeadcountChangePct` | Real | Percentage year-over-year headcount delta |

### 2.7 Simulated trend views

`employees_trend_current`
- latest simulated monthly active roster only
- useful for current-state views that should align to the trend layer rather than the original snapshot

`workforce_trend_latest_summary`
- latest simulated monthly summary rows only
- useful for current top-line trend metrics and the scoped `trend_summary` payload in `/api/stats`

### 2.8 Current report-friendly columns
The built-in standard reports intentionally use a conservative employee-level subset:
- `EmployeeNumber`
- `Department`
- `JobRole`
- `JobLevel`
- `BusinessTravel`
- `OverTime`
- `Attrition`

This keeps reports compatible with restricted roles that only have access to headcount and attrition data.

### 2.9 Constant columns
The following columns should generally be ignored for analysis:
- `EmployeeCount`
- `Over18`
- `StandardHours`

## 3. `access_control.db`

The access-control database is created by [database/access_control.py](database/access_control.py).

### 3.1 Table: `user_access`

| Column | Type | Description |
|---|---|---|
| `email` | Text | Primary key and lookup key from the authenticated user |
| `role` | Text | User-facing role name |
| `scope_name` | Text | Scope label used in the UI |
| `allowed_departments` | Text | JSON-encoded department list |
| `allowed_metrics` | Text | JSON-encoded metric domain list |
| `allowed_doc_tags` | Text | JSON-encoded context document tag list |

### 3.2 Semantics

`allowed_departments`
- empty list means enterprise-wide department access
- non-empty list means all analytics must be restricted to those departments

`allowed_metrics`
- `all` means no metric-domain restrictions
- otherwise values may include:
  - `headcount`
  - `attrition`
  - `compensation`
  - `performance`
  - `satisfaction`
  - `tenure`
  - `demographics`
  - `policy`

`allowed_doc_tags`
- controls which context documents may be retrieved into prompt context

### 3.3 Seeded demo identities

The repo seeds several demo users:

| Email | Role | Scope |
|---|---|---|
| `local@hr-intelligence.local` | HR Admin | Enterprise |
| `demo.microsoft@hr-intelligence.local` | Technology Manager | Research & Development |
| `demo.google@hr-intelligence.local` | HR Business Partner | Research & Development, Sales, Human Resources |
| `demo.okta@hr-intelligence.local` | Policy Lead | Enterprise Policy |

These are useful for local testing, but in a bank deployment they should be replaced by a real authoritative source.

## 4. `context_store.db`

This database is created by [database/context_store.py](database/context_store.py).

### 4.1 Table: `conversation_memory`

| Column | Type | Description |
|---|---|---|
| `id` | Integer | Auto-increment key |
| `user_email` | Text | User identifier |
| `question` | Text | Original user prompt |
| `response` | Text | Final assistant response |
| `insight_summary` | Text | Compact saved summary used for sidebar recall and personalization |
| `created_at` | Text | UTC timestamp |
| `feedback_score` | Integer | `1` for upvoted, `-1` for downvoted, `0` for unrated |
| `feedback_updated_at` | Text | UTC timestamp of the latest feedback action |

Purpose:
- recent and related user memory for prompt context
- storage for curated helpful answers that can be surfaced on similar questions
- sidebar history in the web UI
- saved-chat recall without rerunning the original question
- compact insight reuse for favorite, relevant, and past chat clicks

Retention:
- by default, conversation memory is retained indefinitely
- if `MEMORY_RETENTION_DAYS` is set above `0`, old conversation memory is pruned during writes

Current retrieval patterns built on top of this table:
- `recent_memory`: compact prompt context for the current turn
- `relevant_questions`: strong-match sidebar relevance
- `past_questions_for_sidebar`: broader cross-session history list
- `get_memory`: direct recall lookup for a saved prior chat

Current storage and personalization semantics:
- if a live turn is only a thin follow-up such as `yes`, `show me`, or `answer question 1`, the saved `question` may be promoted to the anchored substantive HR question instead
- favorite-chat ranking aggregates reuse count across repeated asks of the same question
- featured-history and center-board prompt surfaces intentionally filter thin shorthand follow-ups so the UI emphasizes the real business question
- topic labels such as `Headcount`, `Attrition rate`, `Tenure mix`, and `Workforce trends` are derived at retrieval time rather than stored as explicit database columns

### 4.2 Table: `context_documents`

| Column | Type | Description |
|---|---|---|
| `id` | Integer | Auto-increment key |
| `title` | Text | Document title |
| `content` | Text | Document body |
| `tags` | Text | JSON-encoded tag list |
| `created_at` | Text | UTC timestamp |

Purpose:
- policy and schema retrieval
- metric definitions
- future document-grounded guidance

Access behavior:
- document retrieval is filtered by each user's `allowed_doc_tags`
- document management APIs are also checked against allowed tags

### 4.3 Seeded context documents
The repo seeds documents such as:
- HR Analytics Scope Policy
- HR Data Access Policy
- Metric Definitions
- HR Snapshot Calculation Definitions
- Database Schema Summary

## 5. Derived Metrics Used By The Platform

The app currently surfaces or calculates:
- `total_employees`
- `attrited_employees`
- `active_employees`
- `attrition_rate_pct`
- `promoted_last_year_employees`
- department-level `promotion_rate`
- `headcount_mom_change_pct`
- `headcount_yoy_change_pct`
- `monthly_headcount_change`
- `monthly_hiring_rate_pct`
- `monthly_attrition_rate_pct`
- `monthly_promotion_rate_pct`
- `rolling12_hiring_rate_pct`
- `rolling12_attrition_rate_pct`
- `rolling12_promotion_rate_pct`
- `avg_years_at_company`
- `overtime_share_pct`
- `tenure_distribution_pct`

Definitions:
- `total_employees`: total employees in scope
- `attrited_employees`: employees with `Attrition='Yes'` in scope
- `active_employees`: total employees minus attrited employees in scope
- `attrition_rate_pct`: attrited employees divided by total employees times 100
- `promoted_last_year_employees`: employees where `YearsSinceLastPromotion < 1`
- `promotion_rate`: recently promoted employees divided by total headcount in the same slice, multiplied by 100

Snapshot calculation caveat:
- promotion metrics in this demo are current-snapshot calculations, not rolling time-series measures

Trend calculation caveat:
- the trend metrics above come from the simulated monthly layer and should be labeled as simulated when used in analysis or export workflows

Trend integration note:
- these trend metrics are now part of the runtime product contract, not just ad hoc chart fields
- `/api/stats`, proactive tiles, report exports, configured Excel workbooks, and saved memory topic tagging all use the same trend vocabulary

## 6. Access-Controlled Data Domains

Metric domains are mapped to restricted columns in [database/access_control.py](database/access_control.py).

Examples:
- compensation domain includes `MonthlyIncome`, `HourlyRate`, `DailyRate`
- satisfaction domain includes `JobSatisfaction`, `EnvironmentSatisfaction`, `WorkLifeBalance`
- tenure domain includes `YearsAtCompany`, `YearsInCurrentRole`, `YearsSinceLastPromotion`

This is how the repo blocks users from seeing data outside their approved domains.

## 7. Bank Deployment Implications

For an internal bank deployment, the data dictionary should eventually expand to include:
- source HRIS mappings
- employee-manager hierarchy logic
- business unit definitions
- policy document taxonomy
- audit record schema
- retention classes for memory and context records

The current SQLite data model is appropriate for a contained prototype and a strong engineering starting point, but it is not the final governance model for a regulated internal rollout.
