#!env python
import json
import math
import os.path
import re
from pprint import pprint

import pandas as pd
import argparse
import bs4


class GradingDict():
  def __init__(self, cutoffs):
    self.conversions = cutoffs
    self.cutoffs = sorted(list(cutoffs.keys()))
    
  def __getitem__(self, index_val):
    for possible_cutoff in self.cutoffs:
      if index_val >= possible_cutoff:
        continue
      return self.conversions[possible_cutoff]
    return "A+"
  
  @classmethod
  def get_grade_converter(cls, path_to_grading_json=None):
    
    if path_to_grading_json is None:
      conversion_rubric = {
        60: "F",
        70: "D",
        73: "C-",
        77: "C",
        80: "C+",
        83: "B-",
        87: "B",
        90: "B+",
        93: "A-",
        97: "A",
        float("inf"): "A+"
      }
    else:
      with open(path_to_grading_json) as fid:
        conversion_rubric = json.load(fid)
        
    return cls(conversion_rubric)
    
    
def parse_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--round_normally", action="store_true", help="Round normally instead of simply using the ceiling function")
  parser.add_argument("--input_file", default="/Users/ssogden/Documents/CSUMB/Fall2023/CST334/final/2023-12-31T0905_Grades-CST334-M_01-02_FA23.csv")
  parser.add_argument("--input_html", default="/Users/ssogden/Documents/CSUMB/Fall2023/CST334/final/01.html")
  parser.add_argument("--rubric_dict", default=None, help="Path to json file containing rubric dictionary")
  
  return vars(parser.parse_args())

def read_csv(path_to_csv: str) -> pd.DataFrame:
  df = pd.read_csv(path_to_csv)
  df = df[["Student", "SIS User ID", "Final Score", "Unposted Final Score"]]
  df = df.iloc[2:-1]
  df["Final Score"] = df["Final Score"].astype(float)
  return df

def do_rounding(val, round_normally):
  if not round_normally:
    return math.ceil(val)
  return round(val)

def get_student_grade(name_from_html, grades):
  # todo: make it so if there are two students with the same last name it will work still
  possible_matches = list(grades.keys())
  last_name = name_from_html.split(',')[0]
  possible_matches = list(filter((lambda s: s.startswith(last_name)), possible_matches))
  if len(possible_matches) == 1:
    return grades[possible_matches[0]]
  return None

def update_html(input_html, grades):
  with open(input_html) as fid:
    soup = bs4.BeautifulSoup(fid, 'html.parser')
  #print(soup.prettify())
  
  for grade_line in soup.find_all(id=re.compile("^trGRADE_ROSTER\$0_row")):
    # print(grade_line.prettify())
    email_line = grade_line.find(id=re.compile("^DERIVED_SSSMAIL_EMAIL_ADDR\$\d+"))
    student_name = email_line.text
    student_grade = get_student_grade(student_name, grades)
    if student_grade is None:
      continue
    print(f"{student_name} : {get_student_grade(student_name, grades)}")
    #student_sis_name = email_line["href"].split(':')[1].split('@')[0]
    #print(f"{student_sis_name} : {grades[student_sis_name]}")
    #print("\n---------------\n")
    grade_selection = grade_line.find(id=re.compile("^DERIVED_SR_RSTR_CRSE_GRADE_INPUT\$\d+"))
    grade_to_select = grade_selection.find(value=student_grade)
    grade_to_select["selected"] = "selected"
    print(grade_to_select)
    # break
  print(soup.prettify())
  with open(os.path.join(os.path.dirname(input_html), "out.html"), 'w') as fid:
    fid.write(soup.prettify())


def main():
  flags = parse_flags()
  grade_convertor = GradingDict.get_grade_converter(flags["rubric_dict"])
  
  df = read_csv(flags["input_file"])
  print(df)
  
  grades = {}
  for (_, row) in df.iterrows():
    score = row["Final Score"]
    print(f"{row['Student']} ({row['SIS User ID']}) : {grade_convertor[do_rounding(score, flags['round_normally'])]}")
    grades[row["Student"]] = grade_convertor[do_rounding(score, flags['round_normally'])]
    
  print("\n---------------\n")
  update_html(flags["input_html"], grades)

if __name__ == "__main__":
  main()
  