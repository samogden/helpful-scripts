
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple

def _detect_columns(df: pd.DataFrame) -> Dict[str, str]:
    cols_lower = {c.lower(): c for c in df.columns}
    day_cands = ["day", "date"]
    time_cands = ["time"]
    day_col = next((cols_lower[c] for c in day_cands if c in cols_lower), None)
    time_col = next((cols_lower[c] for c in time_cands if c in cols_lower), None)
    if not day_col or not time_col:
        raise ValueError(f"Could not find day/time columns. Saw columns: {list(df.columns)}")
    return {"day": day_col, "time": time_col}

def _to_int_bool(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    out[cols] = out[cols].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
    return out

def _is_top_of_hour(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return True if pd.Series([s]).str.match(r"^(?:\d|1\d|2[0-3]):00:00$").iloc[0] else False

def _fmt_noon_anchored(hour: int) -> Tuple[int, str]:
    hour = int(hour)
    if hour == 0:
        return 12, "pm"
    if 1 <= hour <= 11:
        return hour, "pm"
    if hour == 12:
        return 12, "am"
    return hour - 12, "am"
    
def schedule_office_hours(csv_path: str, max_hours: int, coverage_factor: float = 1.0) -> Dict[str, Any]:
    df = pd.read_csv(csv_path)
    colmap = _detect_columns(df)
    day_col, time_col = colmap["day"], colmap["time"]

    students = df.columns.difference([day_col, time_col])
    df = _to_int_bool(df, list(students))

    # Keep only top-of-hour rows
    df_top = df[df[time_col].apply(_is_top_of_hour)].copy()

    # Identify students who never marked availability (exclude from denominator)
    col_means = df[students].apply(pd.to_numeric, errors="coerce").mean()
    zero_avail_cols = sorted([s for s, m in col_means.items() if m == 0])
    zero_avail_count = len(zero_avail_cols)

    # Precompute available sets per slot
    slot_rows = []
    for idx, row in df_top.iterrows():
        avail = set(row[students][row[students] == 1].index) - set(zero_avail_cols)
        hour = int(str(row[time_col]).split(":")[0])
        slot_rows.append({
            "idx": idx,
            "day": row[day_col],
            "hour_raw": hour,
            "avail": avail,
            "pop": len(avail),   # total availability excluding zero-availability students
        })

    total_students = len(students) - zero_avail_count
    required_coverage = int(np.ceil((len(students)) * coverage_factor)) - zero_avail_count
    required_coverage = max(0, required_coverage)

    covered_students: set = set()
    chosen: List[Dict[str, Any]] = []
    cdf_points: List[Dict[str, Any]] = []

    # Greedy selection: each step pick slot with max marginal gain
    remaining = slot_rows[:]
    for _ in range(max_hours):
        # compute marginal gains
        best = None
        best_gain = 0
        for slot in remaining:
            gain = len(slot["avail"] - covered_students)
            if gain > best_gain or (gain == best_gain and best is not None and slot["pop"] > best["pop"]):
                best = slot
                best_gain = gain

        if best is None or best_gain == 0:
            break  # no more improvement possible

        # take it
        chosen.append({"day": best["day"], "hour_raw": best["hour_raw"]})
        covered_students |= best["avail"]

        denom = max(1, total_students)
        cdf_points.append({
            "day": best["day"],
            "hour_raw": best["hour_raw"],
            "covered_count": len(covered_students),
            "covered_frac": len(covered_students) / denom
        })

        # stop early if we hit the target
        if len(covered_students) >= required_coverage:
            break

        # remove chosen slot from remaining
        remaining = [s for s in remaining if not (s["day"] == best["day"] and s["hour_raw"] == best["hour_raw"])]

    return {
        "selected_slots": chosen,
        "covered_students": len(covered_students),
        "total_students": len(students),
        "target_coverage_factor": coverage_factor,
        "zero_availability_student_count": int(zero_avail_count),
        "students_with_zero_availability": zero_avail_cols,
        "cdf": cdf_points
    }

if __name__ == "__main__":
    import sys
    info = schedule_office_hours(sys.argv[1], max_hours=40, coverage_factor=1.0)
    denom = max(1, (info['total_students'] - info['zero_availability_student_count']))
    print(f"Coverage rate (excluding zero-availability): {100 * (info['covered_students'] / denom):0.2f}%")
    print("\nSelected slots and CDF progress:")
    for i, slot in enumerate(info["cdf"], 1):
        hr, suf = _fmt_noon_anchored(slot["hour_raw"])
        day_time = f"{i:>2}. {slot['day']} @ {hr}{suf}"
        print(f"{day_time:<20}  -> CDF: {slot['covered_frac']*100:0.2f}% "+ f"({slot['covered_count']} / {denom})")
    if info["students_with_zero_availability"]:
        print("\nZero-availability columns:", ", ".join(map(str, info["students_with_zero_availability"])))
    else:
        print("\nNo zero-availability columns detected.")
