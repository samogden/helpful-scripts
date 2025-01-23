import pandas as pd
import numpy as np
import pprint

"""
javascript:(function()%7Bfunction getCSV(%7Bdelimiter%3D"%2C"%2CtimeFormat%3D"12-hour"%7D%3D%7B%7D)%7Bif(%5BPeopleNames%2CPeopleIDs%2CAvailableAtSlot%2CTimeOfSlot%5D.some(v%3D>!Array.isArray(v)%7Cv.length%3D%3D%3D0))%7Bconsole.error("Error%3A One or more required variables (PeopleNames%2C PeopleIDs%2C AvailableAtSlot%2C TimeOfSlot) are undefined or empty.")%3Breturn%3B%7Dlet result%3D%60Day%24%7Bdelimiter%7DTime%24%7Bdelimiter%7D%60%2BPeopleNames.join(delimiter)%2B"%5Cn"%3Bfor(let i%3D0%3Bi<AvailableAtSlot.length%3Bi%2B%2B)%7Blet slotExpr%3D%60%2F%2Fdiv%5B%40id%3D'GroupTime%24%7BTimeOfSlot%5Bi%5D%7D'%5D%2F%40onmouseover%60%3Blet slot%3Ddocument.evaluate(slotExpr%2Cdocument%2Cnull%2CXPathResult.STRING_TYPE%2Cnull).stringValue.match(%2F.*"(.*)".*%2F)%3F.%5B1%5D%3Bif(!slot)%7Bconsole.error(%60Error%3A Could not retrieve or format time slot for index %24%7Bi%7D.%60)%3Bcontinue%3B%7Dlet%5Bday%2Ctime%5D%3Dslot.split(" ")%3Bif(timeFormat%3D%3D%3D"24-hour")%7Btime%3DconvertTo24HourFormat(time)%3B%7Dresult%2B%3D%60%24%7Bday%7D%24%7Bdelimiter%7D%24%7Btime%7D%24%7Bdelimiter%7D%60%3Bresult%2B%3DPeopleIDs.map(id%3D>AvailableAtSlot%5Bi%5D.includes(id)%3F1%3A0).join(delimiter)%3Bresult%2B%3D"%5Cn"%3B%7Dconsole.log(result)%3Breturn result%3Bfunction convertTo24HourFormat(time12h)%7Bconst%5Btime%2Cmodifier%5D%3Dtime12h.split(' ')%3Blet%5Bhours%2Cminutes%2Cseconds%5D%3Dtime.split('%3A')%3Bif(hours%3D%3D%3D'12')%7Bhours%3D'00'%3B%7Dif(modifier%3D%3D%3D'PM')%7Bhours%3DparseInt(hours%2C10)%2B12%3B%7Dreturn%60%24%7Bhours%7D%3A%24%7Bminutes%7D%3A%24%7Bseconds%7D%60%3B%7D%7Dfunction downloadCSV(%7Bfilename%2Cdelimiter%3D"%2C"%2CtimeFormat%3D"12-hour"%7D%3D%7B%7D)%7Bconst urlParams%3Dnew URLSearchParams(window.location.search)%3Bconst uniqueCode%3DurlParams.keys().next().value%7C%7C'UNKNOWNCODE'%3Bconst timestamp%3Dnew Date().toISOString().slice(0%2C19).replace(%2F%5B%3A%5D%2Fg%2C"")%3Bif(!filename)%7Bfilename%3D%60when2meet_%24%7BuniqueCode%7D_%24%7Btimestamp%7D.csv%60%3B%7Dconst content%3DgetCSV(%7Bdelimiter%2CtimeFormat%7D)%3Bif(!content)%7Bconsole.error("Error%3A Failed to generate CSV content.")%3Breturn%3B%7Dconst file%3Dnew Blob(%5Bcontent%5D%2C%7Btype%3A'text%2Fplain'%7D)%3Bconst link%3Ddocument.createElement("a")%3Blink.href%3DURL.createObjectURL(file)%3Blink.download%3Dfilename%3Blink.click()%3BURL.revokeObjectURL(link.href)%3B%7DdownloadCSV(%7Bdelimiter%3A"%2C"%2CtimeFormat%3A"24-hour"%7D)%3B%7D)()
"""

def schedule_office_hours(csv_path, max_hours, coverage_factor=1.0):
    # Load data
    df = pd.read_csv(csv_path)
    

    # Extract student names (all columns except 'date' and 'time')
    students = df.columns.difference(['date', 'time'])

    # Ensure availability columns are numeric (replace invalid values with 0)
    df[students] = df[students].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)

    # Filter to include only time slots starting at round hours
    df = df[df['time'].str.match(r'^(?:\d|1\d|2[0-3]):00:00$')]

    # Add a column for total availability per time slot
    df['total_availability'] = df[students].sum(axis=1)

    # Sort by total availability (descending)
    df = df.sort_values(by='total_availability', ascending=False).reset_index(drop=True)


    print(df.apply(pd.to_numeric, errors='coerce').mean()[df.apply(pd.to_numeric, errors='coerce').mean() == 0].count())

    
    # Initialize tracking
    selected_slots = []
    covered_students = set()
    total_students = len(students)
    required_coverage = int(np.ceil(total_students * coverage_factor))

    # Iteratively select time slots
    for _, row in df.iterrows():
        # Stop if we've reached max hours
        if len(selected_slots) >= max_hours:
            break

        # Find students available in this slot
        available_students = set(row[students][row[students] == 1].index)

        # Add this slot if it covers any uncovered students or if more slots can be added
        if available_students - covered_students or len(selected_slots) < max_hours:
            day = row['date']
            hour = int(row['time'].split(':')[0])
            selected_slots.append({'date' : day, 'time' : hour})
            covered_students.update(available_students)

        # Continue even if required coverage is met, to add more slots
        if len(covered_students) >= required_coverage:
            continue
    
    print('\n'.join(set(students.values) - covered_students))

    # Output results
    return {
        'selected_slots': selected_slots,
        'covered_students': len(covered_students),
        'total_students': total_students,
        'target_coverage_factor': coverage_factor,
        'zero_availability_student_count' : df.apply(pd.to_numeric, errors='coerce').mean()[df.apply(pd.to_numeric, errors='coerce').mean() == 0].count()
    }


# Example usage
info = schedule_office_hours(
        "when2meet_28505930-B6RFr_2025-01-22T222711.csv",
        max_hours=15,  # Increased hours to test flexibility
        coverage_factor=1.0
    )

print("\n\n")

print(f"Coverage Rate: {100*(info['covered_students'] / (info['total_students'] - info['zero_availability_student_count'])) : 0.2f}%")

for slot in info["selected_slots"]:
    print(f"{slot['date']} @ {slot['time']}{'pm' if slot['time'] == 12 or slot['time'] < 8 else 'pm'}")
    
    