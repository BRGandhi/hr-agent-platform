from __future__ import annotations

import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


MONTHS_PER_YEAR = 12

HIRE_SEASONALITY = [0.94, 0.97, 1.02, 1.06, 1.08, 1.03, 1.12, 1.10, 1.02, 0.95, 0.88, 0.83]
EXIT_SEASONALITY = [1.03, 1.01, 0.99, 0.97, 0.96, 0.94, 0.95, 0.97, 1.00, 1.03, 1.06, 1.09]
PROMOTION_SEASONALITY = [0.86, 0.92, 1.18, 1.20, 0.98, 0.91, 0.93, 0.96, 1.06, 1.12, 0.97, 0.91]


@dataclass(frozen=True)
class SimulationConfig:
    latest_snapshot_month: date = date(2026, 3, 1)
    months: int = 36
    annual_hiring_rate: float = 0.20
    annual_attrition_rate: float | None = None
    annual_promotion_rate: float | None = None
    target_latest_headcount: int | None = None
    random_seed: int = 20260415


@dataclass
class EmployeeState:
    employee_number: int
    source_employee_number: int
    department: str
    job_role: str
    job_level: int
    age_months: int
    total_working_months: int
    years_at_company_months: int
    years_in_current_role_months: int
    years_since_last_promotion_months: int
    years_with_curr_manager_months: int
    monthly_income: float
    percent_salary_hike: int
    gender: str
    business_travel: str
    daily_rate: int
    distance_from_home: int
    education: int
    education_field: str
    environment_satisfaction: int
    hourly_rate: int
    job_involvement: int
    job_satisfaction: int
    marital_status: str
    monthly_rate: int
    num_companies_worked: int
    overtime: str
    performance_rating: int
    relationship_satisfaction: int
    stock_option_level: int
    training_times_last_year: int
    work_life_balance: int
    hire_month: date
    origin: str
    hire_this_month: bool = False
    promoted_this_month: bool = False


def add_months(value: date, months: int) -> date:
    year = value.year + ((value.month - 1 + months) // 12)
    month = ((value.month - 1 + months) % 12) + 1
    return date(year, month, 1)


def month_key(value: date) -> str:
    return value.isoformat()


def tenure_band(years_at_company: float) -> str:
    if years_at_company < 2:
        return "0-1"
    if years_at_company < 5:
        return "2-4"
    if years_at_company < 10:
        return "5-9"
    return "10+"


def rounded_years(months: int) -> float:
    return round(months / MONTHS_PER_YEAR, 2)


def normalize_weights(counter: Counter) -> dict:
    total = sum(counter.values()) or 1
    return {key: value / total for key, value in counter.items()}


def smoothed_rate(rows: list[dict], key_fn, numerator_fn, overall_rate: float, alpha: float = 8.0) -> dict:
    grouped: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[key_fn(row)].append(row)
    rates = {}
    for key, items in grouped.items():
        numerator = sum(1 for item in items if numerator_fn(item))
        denominator = len(items)
        rates[key] = (numerator + alpha * overall_rate) / (denominator + alpha)
    return rates


def choose_weighted(items: list, weights: list[float], rng: random.Random):
    if not items:
        raise ValueError("Cannot choose from an empty sequence.")
    total = sum(weight for weight in weights if weight > 0)
    if total <= 0:
        return rng.choice(items)
    pick = rng.random() * total
    running = 0.0
    for item, weight in zip(items, weights):
        if weight <= 0:
            continue
        running += weight
        if running >= pick:
            return item
    return items[-1]


def weighted_sample_without_replacement(items: list, weights: list[float], sample_size: int, rng: random.Random) -> list:
    sample_size = max(0, min(sample_size, len(items)))
    pool = list(items)
    pool_weights = list(weights)
    chosen = []
    for _ in range(sample_size):
        choice = choose_weighted(pool, pool_weights, rng)
        index = pool.index(choice)
        chosen.append(choice)
        pool.pop(index)
        pool_weights.pop(index)
    return chosen


def bounded_count(expected: float, upper_bound: int, rng: random.Random) -> int:
    if upper_bound <= 0 or expected <= 0:
        return 0
    std_dev = max(1.0, math.sqrt(expected))
    lower = max(0, math.floor(expected - 2 * std_dev))
    upper = min(upper_bound, math.ceil(expected + 2 * std_dev))
    sampled = int(round(rng.gauss(expected, std_dev)))
    return max(lower, min(upper, sampled))


def allocate_monthly_targets(total: int, weights: list[float], rng: random.Random) -> list[int]:
    if total <= 0:
        return [0 for _ in weights]
    total_weight = sum(weights) or len(weights)
    raw = []
    for weight in weights:
        expected = total * (weight / total_weight)
        std_dev = max(0.75, math.sqrt(max(expected, 0.1)))
        sampled = rng.gauss(expected, std_dev)
        sampled = max(expected - 2 * std_dev, min(expected + 2 * std_dev, sampled))
        raw.append(max(0.0, sampled))
    raw_total = sum(raw) or 1.0
    scaled = [value * total / raw_total for value in raw]
    base = [int(math.floor(value)) for value in scaled]
    remainder = total - sum(base)
    ranked = sorted(
        range(len(scaled)),
        key=lambda index: (scaled[index] - base[index], weights[index], -index),
        reverse=True,
    )
    for index in ranked[:remainder]:
        base[index] += 1
    return base


def project_final_headcount(
    starting_headcount: int,
    config: SimulationConfig,
    annual_attrition_rate: float,
    annual_promotion_rate: float,
) -> int:
    count_rng = random.Random(config.random_seed)
    current_headcount = starting_headcount
    annual_targets_by_year: dict[int, dict[str, list[int]]] = {}
    for month_index in range(config.months):
        year_index = month_index // MONTHS_PER_YEAR
        month_of_year = month_index % MONTHS_PER_YEAR
        if year_index not in annual_targets_by_year:
            annual_targets_by_year[year_index] = {
                "hires": allocate_monthly_targets(
                    int(round(current_headcount * config.annual_hiring_rate)),
                    HIRE_SEASONALITY,
                    count_rng,
                ),
                "exits": allocate_monthly_targets(
                    int(round(current_headcount * annual_attrition_rate)),
                    EXIT_SEASONALITY,
                    count_rng,
                ),
                "promotions": allocate_monthly_targets(
                    int(round(current_headcount * annual_promotion_rate)),
                    PROMOTION_SEASONALITY,
                    count_rng,
                ),
            }
        targets = annual_targets_by_year[year_index]
        current_headcount = current_headcount - min(current_headcount, targets["exits"][month_of_year]) + targets["hires"][month_of_year]
    return current_headcount


def calibrate_starting_headcount(
    target_latest_headcount: int,
    config: SimulationConfig,
    annual_attrition_rate: float,
    annual_promotion_rate: float,
    initial_guess: int,
) -> int:
    low = max(50, initial_guess - 500)
    high = initial_guess + 500
    while project_final_headcount(high, config, annual_attrition_rate, annual_promotion_rate) < target_latest_headcount:
        high += 250
    while low > 50 and project_final_headcount(low, config, annual_attrition_rate, annual_promotion_rate) > target_latest_headcount:
        low = max(50, low - 250)

    best = initial_guess
    best_diff = abs(project_final_headcount(best, config, annual_attrition_rate, annual_promotion_rate) - target_latest_headcount)
    while low <= high:
        mid = (low + high) // 2
        projected = project_final_headcount(mid, config, annual_attrition_rate, annual_promotion_rate)
        diff = projected - target_latest_headcount
        if abs(diff) < best_diff:
            best = mid
            best_diff = abs(diff)
        if diff < 0:
            low = mid + 1
        elif diff > 0:
            high = mid - 1
        else:
            return mid
    return best


def derive_patterns(base_rows: list[dict]) -> dict:
    active_rows = [row for row in base_rows if str(row["Attrition"]) == "No"]
    total_rows = len(base_rows)
    active_count = len(active_rows)
    overall_attrition_rate = sum(1 for row in base_rows if str(row["Attrition"]) == "Yes") / max(total_rows, 1)
    overall_promotion_rate = (
        sum(1 for row in active_rows if float(row["YearsSinceLastPromotion"] or 0) < 1) / max(active_count, 1)
    )

    active_department_share = normalize_weights(Counter(row["Department"] for row in active_rows))
    active_rows_by_department: dict[str, list[dict]] = defaultdict(list)
    new_hire_pool_by_department: dict[str, list[dict]] = defaultdict(list)
    salary_hikes_by_performance: dict[int, list[int]] = defaultdict(list)
    salary_hikes_by_level: dict[int, list[int]] = defaultdict(list)

    for row in active_rows:
        active_rows_by_department[row["Department"]].append(row)
        if float(row["YearsAtCompany"] or 0) <= 2:
            new_hire_pool_by_department[row["Department"]].append(row)
        salary_hikes_by_performance[int(row["PerformanceRating"] or 3)].append(int(row["PercentSalaryHike"] or 15))
        salary_hikes_by_level[int(row["JobLevel"] or 1)].append(int(row["PercentSalaryHike"] or 15))

    active_role_share_by_department: dict[str, dict] = {}
    for department, department_rows in active_rows_by_department.items():
        active_role_share_by_department[department] = normalize_weights(
            Counter(row["JobRole"] for row in department_rows)
        )
        if not new_hire_pool_by_department[department]:
            new_hire_pool_by_department[department] = department_rows

    attrition_by_department_role = smoothed_rate(
        base_rows,
        lambda row: (row["Department"], row["JobRole"]),
        lambda row: str(row["Attrition"]) == "Yes",
        overall_attrition_rate,
    )
    attrition_by_tenure_band = smoothed_rate(
        base_rows,
        lambda row: tenure_band(float(row["YearsAtCompany"] or 0)),
        lambda row: str(row["Attrition"]) == "Yes",
        overall_attrition_rate,
    )
    attrition_by_overtime = smoothed_rate(
        base_rows,
        lambda row: row["OverTime"],
        lambda row: str(row["Attrition"]) == "Yes",
        overall_attrition_rate,
    )
    promotion_by_job_level = smoothed_rate(
        active_rows,
        lambda row: int(row["JobLevel"] or 1),
        lambda row: float(row["YearsSinceLastPromotion"] or 0) < 1,
        overall_promotion_rate,
    )
    promotion_by_department = smoothed_rate(
        active_rows,
        lambda row: row["Department"],
        lambda row: float(row["YearsSinceLastPromotion"] or 0) < 1,
        overall_promotion_rate,
    )

    return {
        "overall_attrition_rate": overall_attrition_rate,
        "overall_promotion_rate": overall_promotion_rate,
        "active_count": active_count,
        "active_department_share": active_department_share,
        "active_role_share_by_department": active_role_share_by_department,
        "active_rows_by_department": active_rows_by_department,
        "new_hire_pool_by_department": new_hire_pool_by_department,
        "attrition_by_department_role": attrition_by_department_role,
        "attrition_by_tenure_band": attrition_by_tenure_band,
        "attrition_by_overtime": attrition_by_overtime,
        "promotion_by_job_level": promotion_by_job_level,
        "promotion_by_department": promotion_by_department,
        "salary_hikes_by_performance": salary_hikes_by_performance,
        "salary_hikes_by_level": salary_hikes_by_level,
    }


def build_state_from_template(
    template: dict,
    employee_number: int,
    prestart_month: date,
    months_offset: int,
    origin: str,
) -> EmployeeState:
    current_age = int(round(float(template["Age"] or 18) * MONTHS_PER_YEAR))
    current_work_years = int(round(float(template["TotalWorkingYears"] or 0) * MONTHS_PER_YEAR))
    current_tenure = int(round(float(template["YearsAtCompany"] or 0) * MONTHS_PER_YEAR))
    current_role_tenure = int(round(float(template["YearsInCurrentRole"] or 0) * MONTHS_PER_YEAR))
    current_since_promo = int(round(float(template["YearsSinceLastPromotion"] or 0) * MONTHS_PER_YEAR))
    current_with_manager = int(round(float(template["YearsWithCurrManager"] or 0) * MONTHS_PER_YEAR))

    starting_tenure = max(0, current_tenure - months_offset)
    starting_work_years = max(starting_tenure, current_work_years - months_offset)
    starting_age = max(18 * MONTHS_PER_YEAR, current_age - months_offset)
    starting_role_tenure = min(starting_tenure, max(0, current_role_tenure - months_offset))
    starting_since_promo = min(starting_tenure, max(0, current_since_promo - months_offset))
    starting_with_manager = min(starting_tenure, max(0, current_with_manager - months_offset))
    hire_month = add_months(prestart_month, -starting_tenure)

    return EmployeeState(
        employee_number=employee_number,
        source_employee_number=int(template["EmployeeNumber"]),
        department=str(template["Department"]),
        job_role=str(template["JobRole"]),
        job_level=int(template["JobLevel"]),
        age_months=starting_age,
        total_working_months=starting_work_years,
        years_at_company_months=starting_tenure,
        years_in_current_role_months=starting_role_tenure,
        years_since_last_promotion_months=starting_since_promo,
        years_with_curr_manager_months=starting_with_manager,
        monthly_income=float(template["MonthlyIncome"]),
        percent_salary_hike=int(template["PercentSalaryHike"]),
        gender=str(template["Gender"]),
        business_travel=str(template["BusinessTravel"]),
        daily_rate=int(template["DailyRate"]),
        distance_from_home=int(template["DistanceFromHome"]),
        education=int(template["Education"]),
        education_field=str(template["EducationField"]),
        environment_satisfaction=int(template["EnvironmentSatisfaction"]),
        hourly_rate=int(template["HourlyRate"]),
        job_involvement=int(template["JobInvolvement"]),
        job_satisfaction=int(template["JobSatisfaction"]),
        marital_status=str(template["MaritalStatus"]),
        monthly_rate=int(template["MonthlyRate"]),
        num_companies_worked=int(template["NumCompaniesWorked"]),
        overtime=str(template["OverTime"]),
        performance_rating=int(template["PerformanceRating"]),
        relationship_satisfaction=int(template["RelationshipSatisfaction"]),
        stock_option_level=int(template["StockOptionLevel"]),
        training_times_last_year=int(template["TrainingTimesLastYear"]),
        work_life_balance=int(template["WorkLifeBalance"]),
        hire_month=hire_month,
        origin=origin,
    )


def create_new_hire(
    patterns: dict,
    department: str,
    employee_number: int,
    hire_month: date,
    rng: random.Random,
) -> EmployeeState:
    department_pool = patterns["new_hire_pool_by_department"].get(department) or patterns["active_rows_by_department"][department]
    weights = []
    for row in department_pool:
        weight = 3.0 if float(row["YearsAtCompany"] or 0) <= 2 else 1.0
        if str(row["OverTime"]) == "No":
            weight += 0.2
        weights.append(weight)
    template = choose_weighted(department_pool, weights, rng)
    pre_company_months = max(
        0,
        int(round((float(template["TotalWorkingYears"] or 0) - float(template["YearsAtCompany"] or 0)) * MONTHS_PER_YEAR)),
    )
    base_age_months = int(round(float(template["Age"] or 18) * MONTHS_PER_YEAR))
    base_tenure_months = int(round(float(template["YearsAtCompany"] or 0) * MONTHS_PER_YEAR))
    age_months = max(18 * MONTHS_PER_YEAR, base_age_months - base_tenure_months)
    return EmployeeState(
        employee_number=employee_number,
        source_employee_number=int(template["EmployeeNumber"]),
        department=str(template["Department"]),
        job_role=str(template["JobRole"]),
        job_level=int(template["JobLevel"]),
        age_months=age_months,
        total_working_months=pre_company_months,
        years_at_company_months=0,
        years_in_current_role_months=0,
        years_since_last_promotion_months=0,
        years_with_curr_manager_months=0,
        monthly_income=float(template["MonthlyIncome"]),
        percent_salary_hike=int(template["PercentSalaryHike"]),
        gender=str(template["Gender"]),
        business_travel=str(template["BusinessTravel"]),
        daily_rate=int(template["DailyRate"]),
        distance_from_home=int(template["DistanceFromHome"]),
        education=int(template["Education"]),
        education_field=str(template["EducationField"]),
        environment_satisfaction=int(template["EnvironmentSatisfaction"]),
        hourly_rate=int(template["HourlyRate"]),
        job_involvement=int(template["JobInvolvement"]),
        job_satisfaction=int(template["JobSatisfaction"]),
        marital_status=str(template["MaritalStatus"]),
        monthly_rate=int(template["MonthlyRate"]),
        num_companies_worked=int(template["NumCompaniesWorked"]),
        overtime=str(template["OverTime"]),
        performance_rating=int(template["PerformanceRating"]),
        relationship_satisfaction=int(template["RelationshipSatisfaction"]),
        stock_option_level=int(template["StockOptionLevel"]),
        training_times_last_year=int(template["TrainingTimesLastYear"]),
        work_life_balance=int(template["WorkLifeBalance"]),
        hire_month=hire_month,
        origin="hire",
        hire_this_month=True,
    )


def increment_survivor(state: EmployeeState) -> None:
    state.age_months += 1
    state.total_working_months += 1
    state.years_at_company_months += 1
    state.years_in_current_role_months += 1
    state.years_since_last_promotion_months += 1
    state.years_with_curr_manager_months += 1


def apply_promotion(state: EmployeeState, patterns: dict, rng: random.Random) -> None:
    hikes = patterns["salary_hikes_by_performance"].get(state.performance_rating) or patterns["salary_hikes_by_level"].get(state.job_level) or [15]
    state.percent_salary_hike = int(rng.choice(hikes))
    state.monthly_income = round(state.monthly_income * (1 + state.percent_salary_hike / 100.0), 2)
    if state.job_level < 5 and rng.random() < 0.65:
        state.job_level += 1
    state.years_since_last_promotion_months = 0
    state.years_in_current_role_months = 0
    state.years_with_curr_manager_months = 0
    state.promoted_this_month = True


def state_exit_weight(state: EmployeeState, patterns: dict) -> float:
    overall = patterns["overall_attrition_rate"] or 0.01
    segment = patterns["attrition_by_department_role"].get((state.department, state.job_role), overall)
    tenure_rate = patterns["attrition_by_tenure_band"].get(tenure_band(rounded_years(state.years_at_company_months)), overall)
    overtime_rate = patterns["attrition_by_overtime"].get(state.overtime, overall)
    risk = segment * (tenure_rate / overall) * (overtime_rate / overall)
    if state.years_at_company_months < 3:
        risk *= 0.55
    elif state.years_at_company_months < 12:
        risk *= 4.0
    elif state.years_at_company_months < 24:
        risk *= 2.5
    elif state.years_at_company_months < 36:
        risk *= 1.5
    elif state.years_at_company_months >= 120:
        risk *= 0.75
    if state.job_level >= 4:
        risk *= 0.85
    return max(0.001, risk)


def state_promotion_weight(state: EmployeeState, patterns: dict) -> float:
    overall = patterns["overall_promotion_rate"] or 0.01
    level_rate = patterns["promotion_by_job_level"].get(state.job_level, overall)
    department_rate = patterns["promotion_by_department"].get(state.department, overall)
    weight = level_rate * (department_rate / overall)
    if state.years_at_company_months < 6:
        weight *= 0.2
    if state.years_since_last_promotion_months < 6:
        weight *= 0.25
    elif state.years_since_last_promotion_months > 36:
        weight *= 1.2
    return max(0.001, weight)


def build_snapshot_record(state: EmployeeState, snapshot_month: date, is_latest_snapshot: bool) -> dict:
    return {
        "SnapshotMonth": month_key(snapshot_month),
        "SnapshotYear": snapshot_month.year,
        "SnapshotMonthNumber": snapshot_month.month,
        "SnapshotQuarter": ((snapshot_month.month - 1) // 3) + 1,
        "EmployeeNumber": state.employee_number,
        "SourceEmployeeNumber": state.source_employee_number,
        "SyntheticEmployee": 1,
        "IsLatestSnapshot": 1 if is_latest_snapshot else 0,
        "HireDate": month_key(state.hire_month),
        "HireThisMonth": 1 if state.hire_this_month else 0,
        "PromotedThisMonth": 1 if state.promoted_this_month else 0,
        "Age": rounded_years(state.age_months),
        "Attrition": "No",
        "BusinessTravel": state.business_travel,
        "DailyRate": state.daily_rate,
        "Department": state.department,
        "DistanceFromHome": state.distance_from_home,
        "Education": state.education,
        "EducationField": state.education_field,
        "EmployeeCount": 1,
        "EnvironmentSatisfaction": state.environment_satisfaction,
        "Gender": state.gender,
        "HourlyRate": state.hourly_rate,
        "JobInvolvement": state.job_involvement,
        "JobLevel": state.job_level,
        "JobRole": state.job_role,
        "JobSatisfaction": state.job_satisfaction,
        "MaritalStatus": state.marital_status,
        "MonthlyIncome": round(state.monthly_income, 2),
        "MonthlyRate": state.monthly_rate,
        "NumCompaniesWorked": state.num_companies_worked,
        "Over18": "Y",
        "OverTime": state.overtime,
        "PercentSalaryHike": state.percent_salary_hike,
        "PerformanceRating": state.performance_rating,
        "RelationshipSatisfaction": state.relationship_satisfaction,
        "StandardHours": 80,
        "StockOptionLevel": state.stock_option_level,
        "TotalWorkingYears": rounded_years(state.total_working_months),
        "TrainingTimesLastYear": state.training_times_last_year,
        "WorkLifeBalance": state.work_life_balance,
        "YearsAtCompany": rounded_years(state.years_at_company_months),
        "YearsInCurrentRole": rounded_years(state.years_in_current_role_months),
        "YearsSinceLastPromotion": rounded_years(state.years_since_last_promotion_months),
        "YearsWithCurrManager": rounded_years(state.years_with_curr_manager_months),
        "TenureBand": tenure_band(rounded_years(state.years_at_company_months)),
    }


def build_event_record(state: EmployeeState, snapshot_month: date, event_type: str) -> dict:
    return {
        "SnapshotMonth": month_key(snapshot_month),
        "SnapshotYear": snapshot_month.year,
        "SnapshotMonthNumber": snapshot_month.month,
        "EmployeeNumber": state.employee_number,
        "SourceEmployeeNumber": state.source_employee_number,
        "SyntheticEmployee": 1,
        "Department": state.department,
        "JobRole": state.job_role,
        "JobLevel": state.job_level,
        "EventType": event_type,
        "TenureAtEventYears": rounded_years(state.years_at_company_months),
        "YearsSinceLastPromotion": rounded_years(state.years_since_last_promotion_months),
        "MonthlyIncome": round(state.monthly_income, 2),
        "OverTime": state.overtime,
    }


def build_summary_rows(
    snapshot_month: date,
    start_states: list[EmployeeState],
    end_states: list[EmployeeState],
    exits: list[EmployeeState],
) -> list[dict]:
    rows = []
    departments = sorted({state.department for state in end_states} | {state.department for state in start_states})
    groups = [("All", None), *[(department, department) for department in departments]]
    start_by_department = Counter(state.department for state in start_states)
    end_by_department = Counter(state.department for state in end_states)
    exit_by_department = Counter(state.department for state in exits)

    for label, department in groups:
        current_states = end_states if department is None else [state for state in end_states if state.department == department]
        if department is None:
            hires = sum(1 for state in current_states if state.hire_this_month)
            promotions = sum(1 for state in current_states if state.promoted_this_month)
            exits_this_month = len(exits)
            start_count = len(start_states)
            end_count = len(end_states)
        else:
            hires = sum(1 for state in current_states if state.hire_this_month)
            promotions = sum(1 for state in current_states if state.promoted_this_month)
            exits_this_month = exit_by_department[department]
            start_count = start_by_department[department]
            end_count = end_by_department[department]

        avg_headcount = max((start_count + end_count) / 2, 1)
        band_counts = Counter(tenure_band(rounded_years(state.years_at_company_months)) for state in current_states)
        overtime_yes = sum(1 for state in current_states if state.overtime == "Yes")
        rows.append(
            {
                "SnapshotMonth": month_key(snapshot_month),
                "SnapshotYear": snapshot_month.year,
                "SnapshotMonthNumber": snapshot_month.month,
                "Department": label,
                "Headcount": end_count,
                "StartOfMonthHeadcount": start_count,
                "HiresThisMonth": hires,
                "ExitsThisMonth": exits_this_month,
                "PromotionsThisMonth": promotions,
                "NetChangeThisMonth": end_count - start_count,
                "MonthlyHiringRatePct": round(100 * hires / avg_headcount, 2),
                "MonthlyAttritionRatePct": round(100 * exits_this_month / avg_headcount, 2),
                "MonthlyPromotionRatePct": round(100 * promotions / avg_headcount, 2),
                "AverageYearsAtCompany": round(
                    sum(rounded_years(state.years_at_company_months) for state in current_states) / max(len(current_states), 1),
                    2,
                ),
                "AverageYearsSinceLastPromotion": round(
                    sum(rounded_years(state.years_since_last_promotion_months) for state in current_states) / max(len(current_states), 1),
                    2,
                ),
                "AverageMonthlyIncome": round(
                    sum(state.monthly_income for state in current_states) / max(len(current_states), 1),
                    2,
                ),
                "OverTimeSharePct": round(100 * overtime_yes / max(len(current_states), 1), 2),
                "TenureBand0To1Pct": round(100 * band_counts["0-1"] / max(len(current_states), 1), 2),
                "TenureBand2To4Pct": round(100 * band_counts["2-4"] / max(len(current_states), 1), 2),
                "TenureBand5To9Pct": round(100 * band_counts["5-9"] / max(len(current_states), 1), 2),
                "TenureBand10PlusPct": round(100 * band_counts["10+"] / max(len(current_states), 1), 2),
            }
        )
    return rows


def add_trend_derivatives(summary_rows: list[dict]) -> None:
    rows_by_department: dict[str, list[dict]] = defaultdict(list)
    for row in summary_rows:
        rows_by_department[row["Department"]].append(row)

    for rows in rows_by_department.values():
        rows.sort(key=lambda row: row["SnapshotMonth"])
        for index, row in enumerate(rows):
            previous = rows[index - 1] if index > 0 else None
            if previous:
                previous_headcount = previous["Headcount"]
                row["MoMHeadcountChange"] = row["Headcount"] - previous_headcount
                row["MoMHeadcountChangePct"] = round(100 * row["MoMHeadcountChange"] / max(previous_headcount, 1), 2)
            else:
                row["MoMHeadcountChange"] = row["NetChangeThisMonth"]
                row["MoMHeadcountChangePct"] = round(100 * row["NetChangeThisMonth"] / max(row["StartOfMonthHeadcount"], 1), 2)

            trailing = rows[max(0, index - 11): index + 1]
            average_headcount = sum(item["Headcount"] for item in trailing) / max(len(trailing), 1)
            row["Rolling12Hires"] = sum(item["HiresThisMonth"] for item in trailing)
            row["Rolling12Exits"] = sum(item["ExitsThisMonth"] for item in trailing)
            row["Rolling12Promotions"] = sum(item["PromotionsThisMonth"] for item in trailing)
            row["Rolling12HiringRatePct"] = round(100 * row["Rolling12Hires"] / max(average_headcount, 1), 2)
            row["Rolling12AttritionRatePct"] = round(100 * row["Rolling12Exits"] / max(average_headcount, 1), 2)
            row["Rolling12PromotionRatePct"] = round(100 * row["Rolling12Promotions"] / max(average_headcount, 1), 2)

            year_ago = rows[index - 12] if index >= 12 else None
            if year_ago:
                row["YoYHeadcountChange"] = row["Headcount"] - year_ago["Headcount"]
                row["YoYHeadcountChangePct"] = round(100 * row["YoYHeadcountChange"] / max(year_ago["Headcount"], 1), 2)
            else:
                row["YoYHeadcountChange"] = 0
                row["YoYHeadcountChangePct"] = 0.0


def validate_simulation(base_rows: list[dict], summary_rows: list[dict], config: SimulationConfig) -> dict:
    active_base = [row for row in base_rows if str(row["Attrition"]) == "No"]
    latest_month = month_key(config.latest_snapshot_month)
    latest_all = next(row for row in summary_rows if row["SnapshotMonth"] == latest_month and row["Department"] == "All")
    latest_departments = sorted(
        [row for row in summary_rows if row["SnapshotMonth"] == latest_month and row["Department"] != "All"],
        key=lambda row: row["Headcount"],
        reverse=True,
    )

    base_active_count = len(active_base)
    base_recent_promotion_rate = 100 * sum(
        1 for row in active_base if float(row["YearsSinceLastPromotion"] or 0) < 1
    ) / max(base_active_count, 1)
    base_attrition_rate = 100 * sum(1 for row in base_rows if str(row["Attrition"]) == "Yes") / max(len(base_rows), 1)
    base_tenure = normalize_weights(Counter(tenure_band(float(row["YearsAtCompany"] or 0)) for row in active_base))

    completed_year_rows = [
        row
        for row in summary_rows
        if row["Department"] == "All" and int(row["SnapshotMonth"][5:7]) == config.latest_snapshot_month.month
    ]
    latest_year_row = completed_year_rows[-1]
    checks = {
        "headcount_close": abs(latest_all["Headcount"] - base_active_count) <= 20,
        "hiring_rate_close": abs(latest_year_row["Rolling12HiringRatePct"] - (config.annual_hiring_rate * 100)) <= 3.0,
        "attrition_rate_close": abs(latest_year_row["Rolling12AttritionRatePct"] - base_attrition_rate) <= 4.0,
        "promotion_rate_close": abs(latest_year_row["Rolling12PromotionRatePct"] - base_recent_promotion_rate) <= 6.0,
        "department_rank_preserved": [row["Department"] for row in latest_departments] == [
            "Research & Development",
            "Sales",
            "Human Resources",
        ],
        "tenure_distribution_close": all(
            abs((latest_all[f"TenureBand{label.replace('-', 'To').replace('+', 'Plus')}Pct"] / 100) - base_tenure.get(label, 0.0)) <= 0.15
            for label in ("0-1", "2-4", "5-9", "10+")
        ),
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "latest_month": latest_month,
        "latest_headcount": latest_all["Headcount"],
        "latest_rolling_12_hiring_rate_pct": latest_year_row["Rolling12HiringRatePct"],
        "latest_rolling_12_attrition_rate_pct": latest_year_row["Rolling12AttritionRatePct"],
        "latest_rolling_12_promotion_rate_pct": latest_year_row["Rolling12PromotionRatePct"],
    }


def simulate_workforce_history(base_rows: list[dict], config: SimulationConfig) -> dict:
    count_rng = random.Random(config.random_seed)
    state_rng = random.Random(config.random_seed + 1)
    patterns = derive_patterns(base_rows)
    annual_attrition_rate = config.annual_attrition_rate if config.annual_attrition_rate is not None else patterns["overall_attrition_rate"]
    annual_promotion_rate = config.annual_promotion_rate if config.annual_promotion_rate is not None else patterns["overall_promotion_rate"]
    target_latest_headcount = config.target_latest_headcount if config.target_latest_headcount is not None else patterns["active_count"]
    monthly_hiring_rate = (1 + config.annual_hiring_rate) ** (1 / MONTHS_PER_YEAR) - 1
    monthly_attrition_rate = 1 - (1 - annual_attrition_rate) ** (1 / MONTHS_PER_YEAR)
    net_monthly_rate = (1 + monthly_hiring_rate) * (1 - monthly_attrition_rate) - 1
    initial_guess = max(
        50,
        int(round(target_latest_headcount / ((1 + net_monthly_rate) ** max(config.months, 1)))),
    )
    starting_headcount = calibrate_starting_headcount(
        target_latest_headcount,
        config,
        annual_attrition_rate,
        annual_promotion_rate,
        initial_guess,
    )
    prestart_month = add_months(config.latest_snapshot_month, -config.months)
    snapshot_months = [add_months(prestart_month, index + 1) for index in range(config.months)]

    active_pool = [row for row in base_rows if str(row["Attrition"]) == "No"]
    seeded = state_rng.sample(active_pool, starting_headcount) if starting_headcount <= len(active_pool) else [state_rng.choice(active_pool) for _ in range(starting_headcount)]

    next_employee_number = max(int(row["EmployeeNumber"]) for row in base_rows) + 1
    active_states = []
    for template in seeded:
        active_states.append(
            build_state_from_template(
                template,
                employee_number=next_employee_number,
                prestart_month=prestart_month,
                months_offset=config.months,
                origin="seed",
            )
        )
        next_employee_number += 1

    snapshot_records: list[dict] = []
    event_records: list[dict] = []
    summary_rows: list[dict] = []
    annual_targets_by_year: dict[int, dict[str, list[int]]] = {}

    for month_index, snapshot_month in enumerate(snapshot_months):
        year_index = month_index // MONTHS_PER_YEAR
        month_of_year = month_index % MONTHS_PER_YEAR
        if year_index not in annual_targets_by_year:
            year_start_headcount = len(active_states)
            annual_targets_by_year[year_index] = {
                "hires": allocate_monthly_targets(
                    int(round(year_start_headcount * config.annual_hiring_rate)),
                    HIRE_SEASONALITY,
                    count_rng,
                ),
                "exits": allocate_monthly_targets(
                    int(round(year_start_headcount * annual_attrition_rate)),
                    EXIT_SEASONALITY,
                    count_rng,
                ),
                "promotions": allocate_monthly_targets(
                    int(round(year_start_headcount * annual_promotion_rate)),
                    PROMOTION_SEASONALITY,
                    count_rng,
                ),
            }

        targets = annual_targets_by_year[year_index]
        start_states = list(active_states)
        exits_target = min(targets["exits"][month_of_year], len(active_states))
        hires_target = targets["hires"][month_of_year]
        if month_index == len(snapshot_months) - 1:
            projected_end = len(active_states) - exits_target + hires_target
            adjustment = target_latest_headcount - projected_end
            if adjustment > 0:
                hires_target += adjustment
            elif adjustment < 0:
                reducible_hires = min(hires_target, -adjustment)
                hires_target -= reducible_hires
                exits_target = min(len(active_states), exits_target + ((-adjustment) - reducible_hires))

        exit_candidates = list(active_states)
        exit_weights = [state_exit_weight(state, patterns) for state in exit_candidates]
        exiting_states = weighted_sample_without_replacement(exit_candidates, exit_weights, exits_target, state_rng)
        exiting_ids = {state.employee_number for state in exiting_states}
        survivors = [state for state in active_states if state.employee_number not in exiting_ids]

        promotion_candidates = list(survivors)
        promotion_target = min(targets["promotions"][month_of_year], len(promotion_candidates))
        promotion_weights = [state_promotion_weight(state, patterns) for state in promotion_candidates]
        promoted_states = weighted_sample_without_replacement(promotion_candidates, promotion_weights, promotion_target, state_rng)
        promoted_ids = {state.employee_number for state in promoted_states}

        for state in survivors:
            increment_survivor(state)
            if state.employee_number in promoted_ids:
                apply_promotion(state, patterns, state_rng)

        department_items = list(patterns["active_department_share"].items())
        departments = [item[0] for item in department_items]
        department_weights = [item[1] for item in department_items]
        hires = []
        for _ in range(hires_target):
            department = choose_weighted(departments, department_weights, state_rng)
            hires.append(create_new_hire(patterns, department, next_employee_number, snapshot_month, state_rng))
            next_employee_number += 1

        for state in exiting_states:
            event_records.append(build_event_record(state, snapshot_month, "exit"))
        for state in promoted_states:
            event_records.append(build_event_record(state, snapshot_month, "promotion"))
        for state in hires:
            event_records.append(build_event_record(state, snapshot_month, "hire"))

        active_states = survivors + hires
        is_latest_snapshot = snapshot_month == config.latest_snapshot_month
        for state in active_states:
            snapshot_records.append(build_snapshot_record(state, snapshot_month, is_latest_snapshot))
        summary_rows.extend(build_summary_rows(snapshot_month, start_states, active_states, exiting_states))

        for state in active_states:
            state.hire_this_month = False
            state.promoted_this_month = False

    add_trend_derivatives(summary_rows)
    validation = validate_simulation(base_rows, summary_rows, config)
    return {
        "snapshot_records": snapshot_records,
        "event_records": event_records,
        "summary_rows": summary_rows,
        "validation": validation,
        "metadata": {
            "latest_snapshot_month": month_key(config.latest_snapshot_month),
            "months": config.months,
            "annual_hiring_rate": config.annual_hiring_rate,
            "annual_attrition_rate": annual_attrition_rate,
            "annual_promotion_rate": annual_promotion_rate,
            "target_latest_headcount": target_latest_headcount,
            "starting_headcount": starting_headcount,
            "random_seed": config.random_seed,
        },
    }


def load_base_rows(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute("SELECT * FROM employees")
    return [dict(row) for row in cursor.fetchall()]


def write_table(conn: sqlite3.Connection, table_name: str, rows: list[dict]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    if not rows:
        raise ValueError(f"Cannot create {table_name} with no rows.")
    columns = list(rows[0].keys())
    column_defs = ", ".join(
        f"{column} {'INTEGER' if isinstance(rows[0][column], int) else 'REAL' if isinstance(rows[0][column], float) else 'TEXT'}"
        for column in columns
    )
    conn.execute(f"CREATE TABLE {table_name} ({column_defs})")
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, ([row[column] for column in columns] for row in rows))


def materialize_workforce_history(db_path: str | Path, config: SimulationConfig | None = None) -> dict:
    resolved_config = config or SimulationConfig()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        base_rows = load_base_rows(conn)
        result = simulate_workforce_history(base_rows, resolved_config)

        write_table(conn, "employees_monthly_history", result["snapshot_records"])
        write_table(conn, "workforce_monthly_events", result["event_records"])
        write_table(conn, "workforce_monthly_summary", result["summary_rows"])
        metadata_rows = [
            {"key": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else str(value)}
            for key, value in {
                **result["metadata"],
                "validation_summary": result["validation"],
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            }.items()
        ]
        write_table(conn, "workforce_simulation_metadata", metadata_rows)

        conn.execute("DROP VIEW IF EXISTS employees_trend_current")
        conn.execute(
            """
            CREATE VIEW employees_trend_current AS
            SELECT *
            FROM employees_monthly_history
            WHERE SnapshotMonth = (SELECT MAX(SnapshotMonth) FROM employees_monthly_history)
            """
        )
        conn.execute("DROP VIEW IF EXISTS workforce_trend_latest_summary")
        conn.execute(
            """
            CREATE VIEW workforce_trend_latest_summary AS
            SELECT *
            FROM workforce_monthly_summary
            WHERE SnapshotMonth = (SELECT MAX(SnapshotMonth) FROM workforce_monthly_summary)
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_monthly_history_month ON employees_monthly_history (SnapshotMonth)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_monthly_history_dept ON employees_monthly_history (Department)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_monthly_history_employee ON employees_monthly_history (EmployeeNumber)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workforce_monthly_events_month ON workforce_monthly_events (SnapshotMonth)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workforce_monthly_events_dept ON workforce_monthly_events (Department)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workforce_monthly_summary_month ON workforce_monthly_summary (SnapshotMonth)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workforce_monthly_summary_dept ON workforce_monthly_summary (Department)")
        conn.commit()
        return result["metadata"] | {"validation": result["validation"]}
