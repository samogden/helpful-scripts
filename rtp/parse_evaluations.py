#!/usr/bin/env python3
"""
Parse course evaluation HTML files and export quantitative and qualitative
data to CSV files.
"""

import argparse
import csv
import re
from pathlib import Path
from bs4 import BeautifulSoup


def clean_percentage(value):
    """Convert percentage string (e.g., '12.5%') to decimal (0.125)."""
    if isinstance(value, str) and value.endswith('%'):
        try:
            return float(value.rstrip('%')) / 100.0
        except ValueError:
            return value
    return value


def extract_course_mapping(soup):
    """Extract the mapping of keys (A, B, C, D) to course names."""
    mapping = {}

    # Find all course sections in the enrollment table
    course_rows = soup.select('tr.report-entry-border')

    for row in course_rows[:10]:  # Limit to avoid duplicates (appears in both quant and qual sections)
        # Get the course name
        course_link = row.select_one('a[ng-bind="courseSection.CourseSectionDetailedLabel"]')
        if not course_link:
            continue
        course_name = course_link.get_text(strip=True)

        # Get the key (A, B, C, D)
        key_span = row.select_one('span[ng-bind="courseSection.Key"], span[class*="faculty-key-"]')
        if not key_span:
            continue
        key = key_span.get_text(strip=True)

        if key and course_name:
            mapping[key] = course_name

    return mapping


def extract_enrollment_stats(soup):
    """Extract enrollment statistics for each course section."""
    stats = []

    # Find the first enrollment table (quantitative section)
    table = soup.select_one('table.report.table.mobile-list-table')
    if not table:
        return stats

    course_rows = table.select('tbody tr.report-entry-border')

    for row in course_rows:
        course_link = row.select_one('a[ng-bind="courseSection.CourseSectionDetailedLabel"]')
        if not course_link:
            continue

        course_name = course_link.get_text(strip=True)
        key_span = row.select_one('span[class*="faculty-key"]')
        key = key_span.get_text(strip=True) if key_span else ''

        # Extract stats
        stat_cells = row.select('td.stat-answer')
        if len(stat_cells) >= 4:
            stats.append({
                'key': key,
                'course': course_name,
                'report_status': stat_cells[0].get_text(strip=True),
                'enrolled': int(stat_cells[1].get_text(strip=True)),
                'responded': int(stat_cells[2].get_text(strip=True)),
                'response_rate': clean_percentage(stat_cells[3].get_text(strip=True)),
            })

    return stats


def extract_quantitative_data(soup, course_mapping):
    """Extract all quantitative survey responses."""
    data = []

    # Find all question group tables
    question_tables = soup.select('table.question-group.report.table.quantitative')

    for table in question_tables:
        # Get the group caption/text
        caption = table.select_one('caption')
        group_text = caption.get_text(strip=True) if caption else ''

        # Get the response option headers (Outstanding, Very good, etc.)
        header_row = table.select_one('tr.header.answers')
        if not header_row:
            continue

        response_headers = [th.get_text(strip=True)
                          for th in header_row.select('th[ng-repeat*="questionGroup.Headers.Question"]')]

        # Process each question
        question_bodies = table.select('tbody[ng-repeat*="question in questionGroup.Questions"]')

        for tbody in question_bodies:
            # Get question text from first row
            first_row = tbody.select_one('tr.report-response')
            if not first_row:
                continue

            question_th = first_row.select_one('th[ng-bind-html*="question.QuestionText"]')
            question_text = question_th.get_text(strip=True) if question_th else ''

            # Process each course section's responses to this question
            response_rows = tbody.select('tr.report-response')

            for row in response_rows:
                # Get course key
                key_span = row.select_one('td.response-key span[ng-bind="courseSection.Key"]')
                if not key_span:
                    continue
                key = key_span.get_text(strip=True)
                course = course_mapping.get(key, '')

                # Get response frequencies and counts
                response_cells = row.select('td[data-column-header][ng-repeat*="response in courseSection.Responses"]')
                responses_dict = {}

                for i, cell in enumerate(response_cells):
                    if i < len(response_headers):
                        header = response_headers[i]
                        # Extract percentage and count
                        freq_span = cell.select_one('span.ng-binding')
                        count_span = cell.select('span.ng-binding')

                        freq = freq_span.get_text(strip=True) if freq_span else ''
                        count = count_span[1].get_text(strip=True) if len(count_span) > 1 else ''

                        # Clean percentage and convert count to int
                        responses_dict[f'{header}_freq'] = clean_percentage(freq) if freq else ''
                        responses_dict[f'{header}_count'] = int(count) if count else ''

                # Get totals (Mean, Std Dev, Did Not Answer, Total Responses)
                total_cells = row.select('td.stat-answer[ng-repeat*="courseSection.Total"]')

                row_data = {
                    'group': group_text,
                    'question': question_text,
                    'key': key,
                    'course': course,
                    **responses_dict,
                }

                if len(total_cells) >= 4:
                    row_data.update({
                        'mean': float(total_cells[0].get_text(strip=True)),
                        'std_dev': float(total_cells[1].get_text(strip=True)),
                        'did_not_answer': int(total_cells[2].get_text(strip=True)),
                        'total_responses': int(total_cells[3].get_text(strip=True)),
                    })

                data.append(row_data)

    return data


def extract_qualitative_data(soup, course_mapping):
    """Extract all qualitative (comment) responses as a flat list."""
    data = []

    # Find the qualitative section
    qual_section = soup.select('div[ng-repeat="qcm in ctrl.qualitative.QuestionCommentModels"]')

    for question_div in qual_section:
        # Find the question table
        table = question_div.select_one('table.report.qualitative')
        if not table:
            continue

        # Get question text
        question_th = table.select_one('th[ng-bind="qcm.QuestionText"]')
        question_text = question_th.get_text(strip=True) if question_th else 'Unknown Question'

        # Clean up question text
        question_text = question_text.replace('Comments: - ', '').strip()
        if not question_text:
            question_text = 'General Comments'

        # Process each course section's comments
        section_rows = table.select('tr.report-section-wrap')

        for row in section_rows:
            # Get course key
            key_span = row.select_one('span[class*="faculty-key"]')
            if not key_span:
                continue

            # Extract just the key letter (A, B, C, D)
            key_text = key_span.get_text(strip=True)
            course = course_mapping.get(key_text, f'Course {key_text}')

            # Get all comments for this course section
            comment_spans = row.select('li.question-comment-answers span[ng-bind="model.Comment"]')
            comments = [span.get_text(strip=True) for span in comment_spans if span.get_text(strip=True)]

            # Add each comment as a separate row
            for comment in comments:
                data.append({
                    'course': course,
                    'key': key_text,
                    'question': question_text,
                    'comment': comment
                })

    return data


def write_quantitative_csv(data, output_path):
    """Write quantitative data to CSV file."""
    if not data:
        print("No quantitative data to write")
        return

    # Get all unique keys for the CSV header
    all_keys = set()
    for row in data:
        all_keys.update(row.keys())

    # Define preferred column order
    priority_cols = ['group', 'question', 'key', 'course']
    other_cols = sorted([k for k in all_keys if k not in priority_cols])
    fieldnames = priority_cols + other_cols

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    print(f"Wrote {len(data)} rows to {output_path}")


def write_qualitative_csv(data, output_path):
    """Write qualitative data to CSV file."""
    if not data:
        print("No qualitative data to write")
        return

    fieldnames = ['course', 'key', 'question', 'comment']

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    print(f"Wrote {len(data)} comments to {output_path}")


def write_enrollment_csv(stats, output_path):
    """Write enrollment statistics to CSV file."""
    if not stats:
        print("No enrollment data to write")
        return

    fieldnames = ['key', 'course', 'report_status', 'enrolled', 'responded', 'response_rate']

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(stats)

    print(f"Wrote {len(stats)} enrollment records to {output_path}")


def parse_evaluation_file(html_path, output_dir=None):
    """Parse a course evaluation HTML file and extract data."""
    html_path = Path(html_path)

    if output_dir is None:
        output_dir = Path('out')
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate output filenames based on input filename
    base_name = html_path.stem
    quant_csv = output_dir / f"{base_name}_quantitative.csv"
    qual_csv = output_dir / f"{base_name}_qualitative.csv"
    enrollment_csv = output_dir / f"{base_name}_enrollment.csv"

    print(f"Parsing {html_path}...")

    # Read and parse HTML
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    # Extract course mapping
    print("Extracting course mapping...")
    course_mapping = extract_course_mapping(soup)
    print(f"Found courses: {course_mapping}")

    # Extract enrollment statistics
    print("Extracting enrollment statistics...")
    enrollment_stats = extract_enrollment_stats(soup)
    write_enrollment_csv(enrollment_stats, enrollment_csv)

    # Extract quantitative data
    print("Extracting quantitative data...")
    quant_data = extract_quantitative_data(soup, course_mapping)
    write_quantitative_csv(quant_data, quant_csv)

    # Extract qualitative data
    print("Extracting qualitative data...")
    qual_data = extract_qualitative_data(soup, course_mapping)
    write_qualitative_csv(qual_data, qual_csv)

    print("\nDone!")
    print(f"Output files:")
    print(f"  - {enrollment_csv}")
    print(f"  - {quant_csv}")
    print(f"  - {qual_csv}")


def main():
    parser = argparse.ArgumentParser(
        description='Parse course evaluation HTML files and export to CSV files'
    )
    parser.add_argument(
        'html_file',
        help='Path to the course evaluation HTML file'
    )
    parser.add_argument(
        '-o', '--output-dir',
        help='Output directory for generated files (default: out/)',
        default=None
    )

    args = parser.parse_args()

    parse_evaluation_file(args.html_file, args.output_dir)


if __name__ == '__main__':
    main()
