HR_SCHEMA = """
The HR database contains the original IBM HR attrition dataset only.

Use:
- `employees` for the original snapshot data
- `employees_current` as a compatibility view over the same rows

Important:
- This demo dataset is a single snapshot, not a true historical time series.
- Do not invent month-over-month, last-12-month, or synthetic trend analyses.
- If the user asks for trends over time, explain that only the original snapshot is available and offer cross-sectional comparisons instead.

TABLE: employees
Description:
  - One row per employee from the original IBM HR attrition CSV.
  - Use this for headcount, attrition, compensation, tenure, satisfaction, promotion, and demographic analysis.

Core columns:
  - Age
  - Attrition
  - BusinessTravel
  - DailyRate
  - Department
  - DistanceFromHome
  - Education
  - EducationField
  - EmployeeCount
  - EmployeeNumber
  - EnvironmentSatisfaction
  - Gender
  - HourlyRate
  - JobInvolvement
  - JobLevel
  - JobRole
  - JobSatisfaction
  - MaritalStatus
  - MonthlyIncome
  - MonthlyRate
  - NumCompaniesWorked
  - Over18
  - OverTime
  - PercentSalaryHike
  - PerformanceRating
  - RelationshipSatisfaction
  - StandardHours
  - StockOptionLevel
  - TotalWorkingYears
  - TrainingTimesLastYear
  - WorkLifeBalance
  - YearsAtCompany
  - YearsInCurrentRole
  - YearsSinceLastPromotion
  - YearsWithCurrManager

VIEW: employees_current
Description:
  - Compatibility view that mirrors `employees`.
  - Safe to use for current/latest workforce questions.

Guidance:
  - For current or latest questions, `employees_current` is fine.
  - For general analysis, `employees` is also fine.
  - There is no real time-series table in this environment.

EXAMPLE QUERIES:
  -- Current headcount by department
  SELECT Department, COUNT(*) as HeadCount
  FROM employees_current
  GROUP BY Department
  ORDER BY HeadCount DESC;

  -- Attrition rate by department
  SELECT Department,
         COUNT(*) as Total,
         SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
         ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) as AttritionRate
  FROM employees
  GROUP BY Department
  ORDER BY AttritionRate DESC;

  -- Employees promoted within the last year
  SELECT Department,
         COUNT(*) as RecentlyPromotedEmployees
  FROM employees
  WHERE YearsSinceLastPromotion < 1
  GROUP BY Department
  ORDER BY RecentlyPromotedEmployees DESC;

  -- Average salary hike by department
  SELECT Department,
         ROUND(AVG(PercentSalaryHike), 1) as AvgSalaryHike
  FROM employees
  GROUP BY Department
  ORDER BY AvgSalaryHike DESC;
"""
