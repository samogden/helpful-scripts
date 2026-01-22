#!/usr/bin/env python3
import argparse
import ast
import re
from dataclasses import dataclass
from typing import Dict, Any, List, Set, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

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


def _is_url(s: str) -> bool:
    try:
        parsed = urlparse(s)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _parse_js_literal(text: str) -> Any:
    # Best-effort parsing for JS literals (arrays/objects) into Python.
    cleaned = text.strip()
    cleaned = re.sub(r"\bnull\b", "None", cleaned)
    cleaned = re.sub(r"\btrue\b", "True", cleaned)
    cleaned = re.sub(r"\bfalse\b", "False", cleaned)
    cleaned = re.sub(r"\bundefined\b", "None", cleaned)
    cleaned = re.sub(r"new Array\((.*?)\)", r"[\1]", cleaned)
    return ast.literal_eval(cleaned)


def _extract_js_var(html: str, name: str) -> Any:
    pattern = re.compile(
        rf"^\s*(?:var|let|const)?\s*(?:window\.)?{re.escape(name)}\s*=\s*(.*?);",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(html)
    if not match:
        return None
    return _parse_js_literal(match.group(1))


def _extract_js_assignments(html: str, name: str) -> Dict[int, Any]:
    pattern = re.compile(rf"(?:window\.)?{re.escape(name)}\[(\d+)\]\s*=\s*(.*?);")
    assignments = {}
    for idx, value in pattern.findall(html):
        assignments[int(idx)] = _parse_js_literal(value)
    return assignments


def _extract_js_array(html: str, names: List[str]) -> List[Any]:
    for name in names:
        value = _extract_js_var(html, name)
        if isinstance(value, list) and value:
            return value
        if isinstance(value, dict) and value:
            # convert numeric-keyed dict to list if possible
            if all(isinstance(k, int) for k in value.keys()):
                max_idx = max(value.keys())
                out = [None] * (max_idx + 1)
                for k, v in value.items():
                    out[k] = v
                return out
    for name in names:
        assignments = _extract_js_assignments(html, name)
        if assignments:
            max_idx = max(assignments.keys())
            out = [None] * (max_idx + 1)
            for k, v in assignments.items():
                out[k] = v
            return out
    return []


def _extract_js_dict(html: str, names: List[str]) -> Dict[Any, Any]:
    for name in names:
        value = _extract_js_var(html, name)
        if isinstance(value, dict):
            return value
    for name in names:
        assignments = _extract_js_assignments(html, name)
        if assignments:
            return assignments
    return {}


def _extract_available_at_slot(html: str) -> Dict[int, List[int]]:
    pattern = re.compile(r"AvailableAtSlot\[(\d+)\]\.push\((\d+)\)")
    out: Dict[int, List[int]] = {}
    for slot_id, person_id in pattern.findall(html):
        slot_idx = int(slot_id)
        out.setdefault(slot_idx, []).append(int(person_id))
    return out


def _extract_grid_day_labels(html: str) -> List[str]:
    day_map = {
        "Mon": "Monday",
        "Tue": "Tuesday",
        "Wed": "Wednesday",
        "Thu": "Thursday",
        "Fri": "Friday",
        "Sat": "Saturday",
        "Sun": "Sunday",
    }
    pattern = re.compile(r">(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)<")
    labels = []
    for match in pattern.findall(html):
        short = match.strip("><")
        full = day_map.get(short, short)
        if full not in labels:
            labels.append(full)
    return labels


def _extract_grid_start_time(html: str) -> Tuple[int, int]:
    pattern = re.compile(r">(\d{1,2}):00\s*([AP]M)", re.IGNORECASE)
    match = pattern.search(html)
    if not match:
        return 8, 0
    hour24, minute = _parse_time_string_to_hour_minute(f"{match.group(1)}:00{match.group(2)}")
    return hour24, minute


def _extract_grid_time_positions(html: str) -> Dict[int, Tuple[int, int]]:
    pattern = re.compile(r"data-col=\"(\d+)\" data-row=\"(\d+)\" data-time=\"(\d+)\"")
    out: Dict[int, Tuple[int, int]] = {}
    for col, row, tval in pattern.findall(html):
        out[int(tval)] = (int(row), int(col))
    return out


def _parse_time_string_to_hour_minute(s: str) -> Tuple[int, int]:
    raw = s.strip().lower().replace(" ", "")
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?([ap]m)?$", raw)
    if not match:
        raise ValueError(f"Unrecognized time string: {s}")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(4)
    if suffix == "am":
        hour24 = 0 if hour == 12 else hour
    elif suffix == "pm":
        hour24 = 12 if hour == 12 else hour + 12
    else:
        hour24 = hour
    return hour24, minute


def _format_time_no_ampm(hour24: int, minute: int) -> str:
    # Match the existing CSV export style: 12 maps to 0, drop am/pm.
    hour12 = hour24 % 12
    return f"{hour12}:{minute:02d}:00"


def _when2meet_url_to_dataframe(url: str) -> pd.DataFrame:
    url = url.replace("\\?", "?")
    with urlopen(url) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    people = _extract_js_dict(html, ["People", "PeopleList", "PeopleNames"])
    if not people:
        people_list = _extract_js_array(html, ["People", "PeopleList", "PeopleNames"])
    else:
        people_list = []

    available = _extract_js_dict(html, ["AvailableIDs", "Availability", "AvailableTimes"])
    if not available:
        available_list = _extract_js_array(html, ["AvailableIDs", "Availability", "AvailableTimes"])
        if available_list and any(isinstance(v, list) for v in available_list):
            available = {i: v for i, v in enumerate(available_list)}
    if not available:
        available = _extract_available_at_slot(html)
    date_strings = _extract_js_array(html, ["DateStrings", "Dates", "DateList", "DayStrings"])
    time_strings = _extract_js_array(html, ["TimeStrings", "Times", "TimeList"])
    date_of_slots = _extract_js_array(html, ["DateOfSlots", "DatesOfSlots"])
    time_of_slots = _extract_js_array(html, ["TimeOfSlots", "TimesOfSlots", "TimeSlots"])
    if not time_of_slots:
        time_of_slots = _extract_js_array(html, ["TimeOfSlot"])

    if not available or (not date_of_slots and not time_of_slots):
        raise ValueError("Failed to parse When2Meet data from URL; page structure may have changed.")

    people_ids = [i for i in _extract_js_array(html, ["PeopleIDs"]) if i is not None]
    if not people_ids and people:
        people_ids = sorted((int(k) for k in people.keys()), key=int)
    if not people_ids and people_list:
        people_ids = list(range(1, len(people_list) + 1))
    if not people_ids:
        # fallback to any IDs we can infer from availability
        seen_ids = set()
        for ids in available.values():
            if isinstance(ids, list):
                seen_ids.update(int(i) for i in ids)
        people_ids = sorted(seen_ids)

    grid_days = _extract_grid_day_labels(html)
    grid_start_hour, grid_start_minute = _extract_grid_start_time(html)
    grid_positions = _extract_grid_time_positions(html)

    rows = []
    num_slots = min(len(date_of_slots), len(time_of_slots)) if date_of_slots else len(time_of_slots)
    for idx in range(num_slots):
        date_val = date_of_slots[idx] if date_of_slots else None
        if date_val is not None:
            if isinstance(date_val, (int, float)) and date_strings:
                date_str = date_strings[int(date_val)]
            else:
                date_str = str(date_val)
            day = str(date_str).split(",")[0].strip()
        else:
            time_val = time_of_slots[idx]
            row_col = grid_positions.get(int(time_val)) if isinstance(time_val, (int, float, str)) else None
            if row_col is None and grid_days:
                col_count = len(grid_days)
                row_col = (idx // col_count, idx % col_count)
            if row_col is None:
                raise ValueError("Could not determine day/time grid layout from When2Meet HTML.")
            row_idx, col_idx = row_col
            day = grid_days[col_idx] if col_idx < len(grid_days) else f"Day{col_idx + 1}"

        time_val = time_of_slots[idx]
        if isinstance(time_val, (int, float)) and time_strings and 0 <= int(time_val) < len(time_strings):
            hour24, minute = _parse_time_string_to_hour_minute(str(time_strings[int(time_val)]))
        elif date_of_slots and isinstance(time_val, (int, float)) and int(time_val) >= 24:
            minutes = int(time_val)
            hour24, minute = minutes // 60, minutes % 60
        elif date_of_slots:
            hour24, minute = _parse_time_string_to_hour_minute(str(time_val))
        else:
            start_minutes = grid_start_hour * 60 + grid_start_minute
            total_minutes = start_minutes + (row_idx * 15)
            hour24, minute = (total_minutes // 60) % 24, total_minutes % 60
        time_str = _format_time_no_ampm(hour24, minute)

        available_ids = available.get(idx, available.get(str(idx), []))
        available_set = {int(i) for i in available_ids} if isinstance(available_ids, list) else set()

        row = {"Day": day, "Time": time_str}
        for pid in people_ids:
            row[str(pid)] = 1 if pid in available_set else 0
        rows.append(row)

    return pd.DataFrame(rows)



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


def _load_slots_from_dataframe(df: pd.DataFrame) -> Tuple[List[Slot], List[str], str, str]:
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


def load_slots(source: str) -> Tuple[List[Slot], List[str], str, str]:
    if _is_url(source):
        df = _when2meet_url_to_dataframe(source)
    else:
        df = pd.read_csv(source)
    return _load_slots_from_dataframe(df)


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

    # if we hit target coverage and user wants additional suggestions
    additional_suggestions = []
    if suggest_after_100 > 0 and len(covered) >= required_coverage:
        # run greedy algorithm again on remaining slots to find optimal alternative set
        alt_covered: Set[str] = set()
        alt_chosen: List[Slot] = []
        alt_remaining = remaining[:]
        
        for _ in range(suggest_after_100):
            if not alt_remaining:
                break
                
            # find best slot among remaining alternatives
            candidates = []
            for s in alt_remaining:
                gain = len(s.avail - alt_covered)
                candidates.append((gain, s.pop, s.day, s.hour24, s))
            
            candidates.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
            
            if not candidates or candidates[0][0] == 0:
                break
                
            best = candidates[0][4]
            alt_chosen.append(best)
            alt_covered |= best.avail
            
            # remove chosen slot
            alt_remaining = [s for s in alt_remaining if not (s.day == best.day and s.hour24 == best.hour24)]
        
        # calculate cumulative coverage for alternative suggestions
        alt_cdf = []
        alt_cum_covered: Set[str] = set()
        for s in alt_chosen:
            alt_cum_covered |= s.avail
            alt_cdf.append(len(alt_cum_covered))
        
        additional_suggestions = []
        for i, s in enumerate(alt_chosen):
            marginal = len(s.avail - (alt_cum_covered if i == 0 else 
                         set().union(*[chosen.avail for chosen in alt_chosen[:i]])))
            additional_suggestions.append({
                "day": s.day, 
                "hour_raw": s.hour24, 
                "total_avail": s.pop, 
                "marginal_gain": len(s.avail),
                "cumulative_coverage": alt_cdf[i]
            })

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
    
    # show additional high-quality suggestions after target coverage achieved
    if "additional_suggestions" in info and info["additional_suggestions"]:
        target_pct = info["target_coverage_factor"] * 100
        print(f"\nOptimal alternative time slots (since {target_pct:.0f}% coverage achieved):")
        for i, sugg in enumerate(info["additional_suggestions"], 1):
            sugg_hr, sugg_suf = _fmt_noon_anchored(sugg["hour_raw"])
            print(f"  {i}. {sugg['day']} @ {sugg_hr}{sugg_suf} ({sugg['marginal_gain']} students, {sugg['total_avail']} total)")


def main():
    ap = argparse.ArgumentParser(description="Greedy office hours scheduler maximizing marginal coverage.")
    ap.add_argument("source", help="Path to When2Meet-style CSV or a When2Meet URL")
    ap.add_argument("--max-hours", type=int, default=4, help="Max number of office-hour slots to choose")
    ap.add_argument("--coverage", type=float, default=1.0, help="Target coverage factor (0..1)")
    ap.add_argument("--show-alternatives", type=int, default=0, help="Show N alternative time slots for each selection")
    ap.add_argument("--suggest-after-100", type=int, default=0, help="After hitting target coverage, suggest N additional optimal time slots")
    args = ap.parse_args()

    slots, students, _, _ = load_slots(args.source)

    # exclude zero-availability students inside load_slots; remaining student list is post-exclusion
    # (we pass the post-exclusion list into greedy_select)
    # Note: load_slots already removed zero-availability students when building Slot.avail,
    # so students here should be the full list; we recompute exclusion by using avail sets union:
    nonzero_students = sorted(set().union(*[s.avail for s in slots]))
    info = greedy_select(slots, nonzero_students, args.max_hours, args.coverage, args.show_alternatives, args.suggest_after_100)
    print_report(info)


if __name__ == "__main__":
    main()
