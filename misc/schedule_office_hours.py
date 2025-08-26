#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from typing import Dict, Any, List, Set, Tuple

import numpy as np
import pandas as pd


# ---------- Helpers ----------

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
    # accepts H:00:00 or HH:00:00 (24-hour)
    return bool(pd.Series([s]).str.match(r"^(?:\d|1\d|2[0-3]):00:00$").iloc[0])


def _hour_from_time_str(s: str) -> int:
    # expects HH:MM:SS in 24-hour, returns 0..23
    return int(str(s).split(":")[0]) % 24



def _fmt_noon_anchored(hour: int) -> Tuple[int, str]:
    hour = int(hour)
    if hour == 0:
        return 12, "pm"
    if 1 <= hour <= 11:
        return hour, "pm"
    if hour == 12:
        return 12, "am"
    return hour - 12, "am"


# ---------- Core algorithm (greedy set cover) ----------

@dataclass(frozen=True)
class Slot:
    day: str
    hour24: int
    avail: Set[str]   # students available at this slot (excluding zero-availability students)
    pop: int          # total availability count for tie-breaking


def load_slots(csv_path: str) -> Tuple[List[Slot], List[str], str, str]:
    df = pd.read_csv(csv_path)
    colmap = _detect_columns(df)
    day_col, time_col = colmap["day"], colmap["time"]

    students = [c for c in df.columns if c not in (day_col, time_col)]
    df = _to_int_bool(df, students)

    # students with zero availability across entire grid
    col_means = df[students].mean()
    zero_avail_students = {s for s, m in col_means.items() if m == 0}

    df_top = df[df[time_col].apply(_is_top_of_hour)].copy()

    slots: List[Slot] = []
    for _, row in df_top.iterrows():
        avail_students = set(row[students][row[students] == 1].index) - zero_avail_students
        slots.append(
            Slot(
                day=str(row[day_col]),
                hour24=_hour_from_time_str(row[time_col]),
                avail=avail_students,
                pop=len(avail_students),
            )
        )

    return slots, [s for s in students], day_col, time_col


def greedy_select(slots: List[Slot], all_students: List[str], max_hours: int, coverage_factor: float,
                  show_alternatives: int = 0, suggest_after_100: int = 0) -> Dict[str, Any]:
    zero_excluded_total = len(all_students)
    required_coverage = int(np.ceil(zero_excluded_total * coverage_factor))

    covered: Set[str] = set()
    chosen: List[Slot] = []
    cdf: List[Dict[str, Any]] = []

    remaining = slots[:]

    for _ in range(max_hours):
        # pick slot with largest marginal gain; tie-break by overall popularity, then by (day, hour)
        # also collect alternatives if requested
        candidates = []
        
        for s in remaining:
            gain = len(s.avail - covered)
            candidates.append((gain, s.pop, s.day, s.hour24, s))
        
        # sort by gain (desc), then pop (desc), then day/hour (asc)
        candidates.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
        
        if not candidates or candidates[0][0] == 0:
            break  # no improvement possible
            
        best = candidates[0][4]
        best_gain = candidates[0][0]
        
        # collect alternatives for this step
        alternatives = []
        if show_alternatives > 0:
            for i in range(1, min(len(candidates), show_alternatives + 1)):
                gain, pop, day, hour24, slot = candidates[i]
                if gain > 0:  # only show alternatives that provide some benefit
                    alternatives.append({
                        "day": day,
                        "hour_raw": hour24,
                        "marginal_gain": gain,
                        "total_avail": pop
                    })

        chosen.append(best)
        covered |= best.avail

        denom = max(1, zero_excluded_total)
        cdf.append({
            "day": best.day,
            "hour_raw": best.hour24,
            "covered_count": len(covered),
            "covered_frac": len(covered) / denom,
            "alternatives": alternatives
        })

        if len(covered) >= required_coverage:
            break

        # remove chosen slot (dedupe by (day, hour))
        remaining = [s for s in remaining if not (s.day == best.day and s.hour24 == best.hour24)]

    # if we hit 100% coverage and user wants additional suggestions
    additional_suggestions = []
    if suggest_after_100 > 0 and len(covered) >= zero_excluded_total:
        # sort remaining slots by total availability (popularity)
        remaining_sorted = sorted(remaining, key=lambda s: (-s.pop, s.day, s.hour24))
        additional_suggestions = [
            {"day": s.day, "hour_raw": s.hour24, "total_avail": s.pop}
            for s in remaining_sorted[:suggest_after_100]
            if s.pop > 0
        ]

    return {
        "selected_slots": [{"day": s.day, "hour_raw": s.hour24} for s in chosen],
        "covered_students": len(covered),
        "total_students_excl_zero": zero_excluded_total,
        "target_coverage_factor": coverage_factor,
        "cdf": cdf,
        "additional_suggestions": additional_suggestions,
    }


# ---------- CLI / printing ----------

def print_report(info: Dict[str, Any]) -> None:
    denom = max(1, info["total_students_excl_zero"])
    print(f"Coverage rate (excluding zero-availability): {100 * (info['covered_students'] / denom):0.2f}%")
    print("\nSelected slots and CDF progress:")

    # build aligned left-hand side: " N. Day @ 12pm"
    lhs_list = []
    for i, slot in enumerate(info["cdf"], 1):
        hr, suf = _fmt_noon_anchored(slot["hour_raw"])
        lhs_list.append(f"{i:>2}. {slot['day']} @ {hr}{suf}")
    pad = max(len(s) for s in lhs_list) if lhs_list else 0

    for (i, slot), s in zip(enumerate(info["cdf"], 1), lhs_list):
        print(f"{s:<{pad}}  -> CDF: {slot['covered_frac']*100:0.2f}% ({slot['covered_count']} / {denom})")
        
        # show alternatives if they exist
        if "alternatives" in slot and slot["alternatives"]:
            print(f"{'':>{pad+2}}   Alternatives:")
            for alt in slot["alternatives"]:
                alt_hr, alt_suf = _fmt_noon_anchored(alt["hour_raw"])
                print(f"{'':>{pad+2}}     {alt['day']} @ {alt_hr}{alt_suf} (+{alt['marginal_gain']} students, {alt['total_avail']} total)")
    
    # show additional high-quality suggestions after 100% coverage
    if "additional_suggestions" in info and info["additional_suggestions"]:
        print(f"\nAdditional high-quality time slots (since 100% coverage achieved):")
        for sugg in info["additional_suggestions"]:
            sugg_hr, sugg_suf = _fmt_noon_anchored(sugg["hour_raw"])
            print(f"  {sugg['day']} @ {sugg_hr}{sugg_suf} ({sugg['total_avail']} students available)")


def main():
    ap = argparse.ArgumentParser(description="Greedy office hours scheduler maximizing marginal coverage.")
    ap.add_argument("csv_path", help="Path to When2Meet-style CSV")
    ap.add_argument("--max-hours", type=int, default=4, help="Max number of office-hour slots to choose")
    ap.add_argument("--coverage", type=float, default=1.0, help="Target coverage factor (0..1)")
    ap.add_argument("--show-alternatives", type=int, default=0, help="Show N alternative time slots for each selection")
    ap.add_argument("--suggest-after-100", type=int, default=0, help="After hitting 100% coverage, suggest N additional high-quality time slots")
    args = ap.parse_args()

    slots, students, _, _ = load_slots(args.csv_path)

    # exclude zero-availability students inside load_slots; remaining student list is post-exclusion
    # (we pass the post-exclusion list into greedy_select)
    # Note: load_slots already removed zero-availability students when building Slot.avail,
    # so students here should be the full list; we recompute exclusion by using avail sets union:
    nonzero_students = sorted(set().union(*[s.avail for s in slots]))
    info = greedy_select(slots, nonzero_students, args.max_hours, args.coverage, args.show_alternatives, args.suggest_after_100)
    print_report(info)


if __name__ == "__main__":
    main()
