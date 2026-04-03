# Data Dictionary

This document describes the data model used by the HR Insights Platform. The repo currently uses three SQLite databases:
- `hr_data.db`
- `access_control.db`
- `context_store.db`

Together, they provide:
- workforce analytics data
- authorization and scoping data
- memory and contextual reference data

## 1. Logical Data Model

### 1.1 `hr_data.db`
Primary analytics database containing the `employees` table.

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

Expected runtime table:
- `employees`

### 2.1 Row and column counts
- rows: 1,470
- columns: 35

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

### 2.4 Current report-friendly columns
The built-in standard reports intentionally use a conservative employee-level subset:
- `EmployeeNumber`
- `Department`
- `JobRole`
- `JobLevel`
- `BusinessTravel`
- `OverTime`
- `Attrition`

This keeps reports compatible with restricted roles that only have access to headcount and attrition data.

### 2.5 Constant columns
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
- Database Schema Summary

## 5. Derived Metrics Used By The Platform

The app currently surfaces or calculates:
- `total_employees`
- `attrited_employees`
- `active_employees`
- `attrition_rate_pct`

Definitions:
- `total_employees`: total employees in scope
- `attrited_employees`: employees with `Attrition='Yes'` in scope
- `active_employees`: total employees minus attrited employees in scope
- `attrition_rate_pct`: attrited employees divided by total employees times 100

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
