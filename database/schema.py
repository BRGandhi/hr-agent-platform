HR_SCHEMA = """
The HR database contains one table: employees

TABLE: employees
Columns:
  - Age                     INTEGER   Employee age in years
  - Attrition               TEXT      Whether employee left: 'Yes' or 'No'
  - BusinessTravel          TEXT      Travel frequency: 'Non-Travel', 'Travel_Rarely', 'Travel_Frequently'
  - DailyRate               INTEGER   Daily rate (compensation metric)
  - Department              TEXT      Department: 'Sales', 'Research & Development', 'Human Resources'
  - DistanceFromHome        INTEGER   Distance from home in miles
  - Education               INTEGER   Education level: 1=Below College, 2=College, 3=Bachelor, 4=Master, 5=Doctor
  - EducationField          TEXT      Field: 'Life Sciences', 'Medical', 'Marketing', 'Technical Degree', 'Human Resources', 'Other'
  - EmployeeCount           INTEGER   Always 1 (row-level constant)
  - EmployeeNumber          INTEGER   Unique employee ID
  - EnvironmentSatisfaction INTEGER   1=Low, 2=Medium, 3=High, 4=Very High
  - Gender                  TEXT      'Male' or 'Female'
  - HourlyRate              INTEGER   Hourly rate
  - JobInvolvement          INTEGER   1=Low, 2=Medium, 3=High, 4=Very High
  - JobLevel                INTEGER   1 (Entry) to 5 (Executive)
  - JobRole                 TEXT      Role: 'Sales Executive', 'Research Scientist', 'Laboratory Technician',
                                        'Manufacturing Director', 'Healthcare Representative', 'Manager',
                                        'Sales Representative', 'Research Director', 'Human Resources'
  - JobSatisfaction         INTEGER   1=Low, 2=Medium, 3=High, 4=Very High
  - MaritalStatus           TEXT      'Single', 'Married', 'Divorced'
  - MonthlyIncome           INTEGER   Monthly income in dollars
  - MonthlyRate             INTEGER   Monthly rate
  - NumCompaniesWorked      INTEGER   Number of companies previously worked at
  - Over18                  TEXT      Always 'Y'
  - OverTime                TEXT      Whether works overtime: 'Yes' or 'No'
  - PercentSalaryHike       INTEGER   Last salary hike percentage
  - PerformanceRating       INTEGER   1=Low, 2=Good, 3=Excellent, 4=Outstanding
  - RelationshipSatisfaction INTEGER  1=Low, 2=Medium, 3=High, 4=Very High
  - StandardHours           INTEGER   Always 80
  - StockOptionLevel        INTEGER   0=None, 1=Low, 2=Medium, 3=High
  - TotalWorkingYears       INTEGER   Total years of work experience
  - TrainingTimesLastYear   INTEGER   Number of training sessions last year
  - WorkLifeBalance         INTEGER   1=Bad, 2=Good, 3=Better, 4=Best
  - YearsAtCompany          INTEGER   Years at current company
  - YearsInCurrentRole      INTEGER   Years in current role
  - YearsSinceLastPromotion INTEGER   Years since last promotion
  - YearsWithCurrManager    INTEGER   Years working under current manager

Total rows: 1,470 employees

EXAMPLE QUERIES:
  -- Count attrition
  SELECT Attrition, COUNT(*) as Count FROM employees GROUP BY Attrition;

  -- Attrition rate by department
  SELECT Department,
         COUNT(*) as Total,
         SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) as Attrited,
         ROUND(100.0 * SUM(CASE WHEN Attrition='Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) as AttritionRate
  FROM employees GROUP BY Department ORDER BY AttritionRate DESC;

  -- Average salary by job role
  SELECT JobRole, ROUND(AVG(MonthlyIncome), 0) as AvgIncome, COUNT(*) as HeadCount
  FROM employees GROUP BY JobRole ORDER BY AvgIncome DESC;
"""
