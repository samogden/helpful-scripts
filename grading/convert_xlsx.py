#! env python
"""IA Grading assistant -- converts from XLSX and HTML to HTML and comments

Adapted from script by Shuwen Liu

"""

import logging
import os
import argparse
import shutil
import zipfile
import json

import numpy as np
import pandas as pd
import bs4


class AssignmentNumberException(Exception):
  pass


def get_default_score_func(override_default_scores=None):
  if override_default_scores is not None:
    default_scores = override_default_scores
  else:
    ## Add new default scores here
    default_scores = {
      0 : 0.,
    }

  def default_score_func(idx):
    try:
      return default_scores[idx]
    except KeyError:
      return 0.
  return default_score_func


def get_default_answers_func(override_default_answers=None):
  if override_default_answers is not None:
    default_answers = override_default_answers
  else:
    ## Add new default answers here
    default_answers = {
      0 : "(No specific comments)",
    }

  def default_answers_func(idx):
    try:
      return default_answers[idx]
    except KeyError:
      return "(No specific comments)"
  return default_answers_func



class Student(object):
  def __init__(self, student_name, username, grader, scores, comments):
    self.student_name = self.__class__.fix_name(student_name)
    self.username = username
    self.grader= grader
    self.scores = [float(f) for f in scores]
    self.comments = comments

  @staticmethod
  def fix_name(name):
    try:
      surname, firname = name.split(",")
      surname = surname.strip()
      firname = firname.strip()
      return f"{firname} {surname}"
    except Exception as e:
      return name

  def __str__(self):
    return f"{self.student_name} ({self.username}) : {np.sum(self.scores)}={'+'.join([str(s) for s in self.scores])} : {'|'.join(self.comments)}"

  def get_comment(self):
    comment_str = ""
    comment_str += f"{self.student_name} ({self.username})\n"
    comment_str += "\n"
    comment_str += f"Comments:\n"
    for idx, (score, comment) in enumerate(zip(self.scores, self.comments)):
      comment_str += f"  Q{idx + 1} : {score} points : {comment}\n"
    comment_str += "\n"
    comment_str += f"Total Score : {np.sum(self.scores)} = {' + '.join([str(s) for s in self.scores])}"
    comment_str += f"\ngraded by: {self.grader}"
    return comment_str

  def get_score(self):
    return np.sum(self.scores)
  
  def is_empty(self):
    return self.get_score() == 0
  
  def missing_question(self):
    return min(self.scores) == 0 and (not self.scores[0] == 0 and len(self.scores) > 3)
  
  def has_potential_errors(self):
    
    if self.is_empty():
      # If there is no grade for the student
      #  Note: this is a subset of the following
      return True
      
    if self.missing_question():
      # If the student has one more more 0s
      return True
    
    
    
    return False
  

def load_excel_to_students_dict(
    path_to_excel,
    default_score_func,
    default_answer_func):
  """Takes an xlsx file and returns a dictionary of student objects with keys of student name"""
  file_extension = os.path.splitext(path_to_excel)[1]
  if file_extension == '.xlsx':
    df = pd.read_excel(path_to_excel, engine='openpyxl')
  elif file_extension == '.xls':
      df = pd.read_excel(path_to_excel)
  elif file_extension == '.csv':
      df = pd.read_csv(path_to_excel)
  
  # Combines alternating columns and assumes they're (score, comment) pairs
  question_comment_column_header_pairs = list(zip(df.columns[3::2], df.columns[4::2]))

  df["Grader"] = df["Grader"].fillna("(This assignment seems to have not been graded.  Please reach out to ask why.)")
  for idx, (q_header, c_header) in enumerate(question_comment_column_header_pairs):
    df[q_header] = df[q_header].fillna(default_score_func(idx))
    df[c_header] = df[c_header].fillna(default_answer_func(idx))

  students = {}
  for _, row in df.iterrows():
    if pd.isna(row["Student Name"]):
      continue
    scores = [
      row[q_header]
      for idx, (q_header, c_header) in enumerate(question_comment_column_header_pairs)
    ]
    comments = [
      row[c_header]
      for idx, (q_header, c_header) in enumerate(question_comment_column_header_pairs)
    ]
    student = Student(
      row["Student Name"],
      row["User Name"],
      row["Grader"],
      scores,
      comments
    )
    students[student.student_name] = student

  return students


def load_and_update_html(path_to_html, students_dict, assignment_number, supress_assignment_number):
  """Loads HTML via beautiful soup and uses the student dict to update scores in place.  Returns string"""
  table_soup = bs4.BeautifulSoup(open(path_to_html).read(), features="html.parser")
  found_assignment = table_soup.find_all("input")[0]
  found_assignment_number = found_assignment["value"]
  # Check to make sure we're doing the same assignment
  if not supress_assignment_number:
    print(f"assignment_number: {assignment_number}")
    print(f"found_assignment_number: {found_assignment_number}")
    if assignment_number != found_assignment_number:
      raise AssignmentNumberException(f"Incorrect assignment number found! {assignment_number} != {found_assignment_number}")
  else:
    found_assignment["value"] = assignment_number

  rows = table_soup.find_all("tr")
  html_students = []
  for row in rows[1:]:  # Skip the first because it's the header
    record = row.find_all("td")
    name = record[0].text.strip()
    html_students.append(name)
    input = record[2].find("input")
    try:
      input["value"] = students_dict[name].get_score()
    except KeyError as e:
      logging.warning("Cannot find score for student {name}")
      logging.warning(e)
  missing_from_html = set(students_dict.keys()).difference(set(html_students))
  missing_from_xlsx = set(html_students).difference(students_dict.keys())
  return table_soup.prettify(), missing_from_html, missing_from_xlsx


def parse_args():
  parser = argparse.ArgumentParser()

  parser.add_argument("--assignment_name", required=True)
  parser.add_argument("--overwrite_existing", action="store_true")

  parser.add_argument("--grades_excel", required=True)
  parser.add_argument("--base_html", required=True)
  parser.add_argument("--default_answers_json")
  
  parser.add_argument("--assignment_number", default=None)
  parser.add_argument("--suppress_assignment_number", action="store_true")

  return parser.parse_args()


def main():
  args = parse_args()

  output_dir = args.assignment_name
  if os.path.exists(output_dir):
    if not args.overwrite_existing:
      logging.error(
        "Assignment output folder already exists.  Please use --overwrite_existing if you wish to overwrite")
      exit(0)
    shutil.rmtree(output_dir)
  os.mkdir(output_dir)
  
  if args.default_answers_json is not None:
    with open(args.default_answers_json) as json_fid:
      default_answers_dict = json.load(json_fid)
    default_answers = [d["default_answer"] for d in default_answers_dict]
    default_scores = [d["default_score"] for d in default_answers_dict]
  else:
    default_answers = None
    default_scores = None
  
  students_dict = load_excel_to_students_dict(
    args.grades_excel, 
    default_score_func=get_default_score_func(default_scores), 
    default_answer_func=get_default_answers_func(default_answers)
  )
  try:
    new_html, missing_from_html, missing_from_xlsx = load_and_update_html(
      args.base_html,
      students_dict,
      args.assignment_number,
      args.suppress_assignment_number
    )
  except AssignmentNumberException as e:
    logging.error(e)
    exit(0)

  with open(os.path.join(output_dir, f"{args.assignment_name}_table.html"), 'w') as o_fid:
    o_fid.write(new_html)

  with zipfile.ZipFile(os.path.join(output_dir, f"{args.assignment_name}_comments.zip"), 'w') as z_fid:
    for student in students_dict.values():
      z_fid.writestr(
        os.path.join("comments", f"{student.username}.txt"),
        student.get_comment()
      )

  if len(missing_from_html) > 0:
    print("!! Missing Students from HTML !!")
    for student in missing_from_html:
      print(f"  Missing entry in html for {student}")

  if len(missing_from_xlsx) > 0:
    print("!! Missing Students from XLSX !!")
    for student in missing_from_xlsx:
      print(f"  Missing entry in xlsx for {student}")

  print("")

  students_with_potential_issues = list(filter((lambda s: s.has_potential_errors()), students_dict.values()))
  if len(students_with_potential_issues) > 0:
    print("!! Students with potential issues!!")
    print("  Missing Question:")
    for student in filter( (lambda s: s.missing_question() and not s.is_empty()), students_with_potential_issues):
      print(f"    Student: {student}")
    print("")
    print("  Empty Score:")
    for student in filter( (lambda s: not(s.missing_question() and not s.is_empty())), students_with_potential_issues):
      print(f"    Student: {student}")
  else:
    print("All students have no issues")

  return


if __name__ == "__main__":
  main()
