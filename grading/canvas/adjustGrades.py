#!env python

from __future__ import annotations

import json
import os
import re
import shutil

import pandas as pd

import logging
logging.basicConfig()
log = logging.getLogger(__file__)
log.setLevel(logging.DEBUG)

CSV_FILE = os.path.expanduser( '/Users/ogde4860/classes/CST334 - OS/OS-Ogden-Fall22/exams/exam1/exam1-score-adjustment/scratch/Exam 1 Quiz Student Analysis Report.csv')
RUBRIC_FILE = os.path.abspath("keys/cst334-fall2022-exam1.json")
QUESTIONS_TO_REDO = [
  "1166835",
  "1166836",
  "1166840"
]
FEEDBACK_DIR = os.path.expanduser("~/classes/CST334 - OS/OS-Ogden-Fall22/exams/exam1/exam1-score-adjustment/scratch/feedback")

class RubricEntry(object):
  def __init__(self, answer_id, rubric_values, is_extra_credit):
    self.answer_id = answer_id
    self.rubric_values = { float(score) : possible_answers for score, possible_answers in rubric_values.items()}
    self.is_extra_credit = is_extra_credit
  def __str__(self):
    return f"<{self.__class__.__name__}:{sorted(self.rubric_values.keys())}>"
  def grade(self, answer):
    for score in sorted(self.rubric_values.keys(), reverse=True):
      log.debug(f"Checking {answer} in {self.rubric_values[score]} ({str(answer) in self.rubric_values[score]})")
      if str(answer) in self.rubric_values[score]:
        return score
    log.info(f"Answer \"{answer}\" not found in rubric ({self.rubric_values.values()}")
    return 0.0

class Rubric(object):
    
  def __init__(self, rubric_dict: dict):
    self.entries = {
      key: RubricEntry(
        key,
        entry["rubric"],
        (entry["is_extra_credit"] if "is_extra_credit" in entry else False)
      )
      for key, entry in rubric_dict.items()
    }
  def __str__(self):
    return f"<{self.__class__.__name__}: {len(self.entries)} entries>"
  
  @classmethod
  def parse_rubric_file(cls, rubric_file) -> Rubric:
    rubric = json.load(open(rubric_file))
    return cls(rubric)

class Question(object):
  def __init__(self, question_id, value, question_col, value_col):
    self.question_id = question_id
    self.value = float(value)
    self.question_col = question_col
    self.value_col = value_col
    self.rubric = None
  def add_rubric(self, rubric: RubricEntry):
    log.debug(f"Adding rubric: {rubric}")
    self.rubric = rubric
  @property
  def has_rubric(self):
    return self.rubric is not None
  def get_contribution_to_total(self):
    if self.has_rubric and self.rubric.is_extra_credit:
      return 0
    else:
      return self.value
  def is_extra_credit(self):
    return self.has_rubric and self.rubric.is_extra_credit

class Response(object):
  def __init__(self, question, response, autograde_score):
    self.question = question
    self.response = response
    self.autograde_score = autograde_score
    self.adjusted_score = None
  @property
  def score(self):
    if self.question.has_rubric:
      calculated_score = self.question.value * self.question.rubric.grade(self.response)
      if calculated_score < self.autograde_score:
        log.warning(f"{calculated_score} < {self.autograde_score}")
        log.debug(f"{self.question.question_col}")
        log.info(f"{self.response}")
      return self.question.value * self.question.rubric.grade(self.response)
    return self.autograde_score
  def __str__(self):
    return f"<{self.__class__.__name__}:{self.score}:{self.response}>"

class Student(object):
  def __init__(self, name, id, sis_id, section, section_id, section_sis_id, submitted, attempt):
    self.name = name
    self.id = id
    self.sis_id = sis_id
    self.section = section
    self.section_id = section_id
    self.section_sis_id = section_sis_id
    self.submitted = submitted
    self.attempt = attempt
    self.responses = dict()
  def get_num_correct(self):
    return len(list(filter((lambda r: r.score != 0), self.responses.values())))
  def get_num_incorrect(self):
    return len(list(filter((lambda r: r.score == 0), self.responses.values())))
  def get_score(self):
    return 100.0 * sum([q.score for q in self.responses.values()]) / sum([q.question.get_contribution_to_total() for q in self.responses.values()])
  def addResponse(self, response):
    self.responses[response.question.question_id] = response
  def to_list(self, skip_questions=True):
    student_list = [
      self.name,
      self.id,
      self.sis_id,
      self.section,
      self.section_id,
      self.section_sis_id,
      self.submitted,
      self.attempt
    ]
    if not skip_questions:
      for question_id in sorted(self.responses.keys()):
        student_list.append(self.responses[question_id].response)
        student_list.append(self.responses[question_id].score)
    student_list.append(self.get_num_correct())
    student_list.append(self.get_num_incorrect())
    student_list.append(self.get_score())
    return student_list

  def to_dict(self, skip_questions=True):
    student_dict = {
      "name" : self.name,
      "id" : self.id,
      "sis_id" : self.sis_id,
      "section" : self.section,
      "section_id" : self.section_id,
      "section_sis_id" : self.section_sis_id,
      "submitted" : self.submitted,
      "attempt" : self.attempt
    }
    if not skip_questions:
      for response in self.responses.values():
        student_dict[response.question.question_col] = response.response
        student_dict[response.question.value_col] = response.score
    student_dict["n correct"] = self.get_num_correct()
    student_dict["n incorrect"] = self.get_num_incorrect()
    student_dict["score"] = self.get_score()
    return student_dict


def get_questions(list_of_columns: list) -> dict[str, Question]:
  questions = {}
  question_pattern = re.compile("\d+: .*")
  for i, col in enumerate(list_of_columns):
    if (re.match(question_pattern, list_of_columns[i])
        and re.match("\d+", list_of_columns[i+1])): # todo: this might throw an error but unlikely
      question_col = list_of_columns[i]
      value_col = list_of_columns[i+1]
      question_id = question_col.split(':')[0]
      value = value_col.split('.')[0] # todo: don't just split?
      questions[question_id] = Question(question_id, value, question_col, value_col)
  return questions
  

def parse_rubric_file(rubric_file):
  rubric = Rubric.parse_rubric_file(rubric_file)
  log.debug(rubric)
  return rubric

def getResponses(row, questions) -> list[Response]:
  responses = []
  for question in questions.values():
    responses.append(Response(question, row[question.question_col], row[question.value_col]))
  return responses

def parse_csv_file(csv_file):
  grades_df = pd.read_csv(csv_file, header=0)
  columns = list(grades_df.columns.values)
  
  questions = get_questions(columns)
  students = []
  for index, row in grades_df.iterrows():
    log.debug(row["name"])
    student = Student(
      row["name"],
      row["id"],
      row["sis_id"],
      row["section"],
      row["section_id"],
      row["section_sis_id"],
      row["submitted"],
      row["attempt"],
    )
    for response in getResponses(row, questions):
      student.addResponse(response)
    students.append(student)

  return columns, students, questions

def getFeedback(questions: dict[str,Question], row):
  feedback_lines = []

  for i, (q_name, q) in enumerate(questions.items()):
    if q_name in QUESTIONS_TO_REDO:
      if row[q.value_col] != q.value:
        feedback_lines.append(f"You can redo Q{i} ({q.question_id}) for points back!")
  
  if len(feedback_lines) != 0:
    feedback_lines.extend(['', '---', ''])

  #for i, (q_name, q) in enumerate(sorted(questions.items(), key=(lambda s: s[0]))):
  for i, (q_name, q) in enumerate(questions.items()):
    feedback_lines.append(f"{'' if (row[q.value_col] == q.value) else '* '}Q{i+1} ({q.question_id}): {row[q.value_col]:.2f} / {q.value}") # : {q_name}") # : {row[q.question_col]}") # : {q.question_col}")
    if q.is_extra_credit():
      feedback_lines[-1] += " (Extra Credit)"
  feedback_lines.append('---')
  feedback_lines.append(f"Score: {row['score']:0.2f}%")
  feedback = '\n'.join(feedback_lines)
  #log.debug(feedback)
  for idx in row.index:
    log.debug(f"{idx[:40]} : {row[idx]}")
  return feedback
  

def main():
  rubric = parse_rubric_file(RUBRIC_FILE)
  headers, students, questions = parse_csv_file(CSV_FILE)
  df = pd.DataFrame([s.to_list(False) for s in students], columns = headers)
  print(df["score"].describe())
  
  
  for question_id, question in questions.items():
   if question_id in rubric.entries:
     question.add_rubric(rubric.entries[question_id])
     #question.rubric = rubric.entries[question_id]
  df = pd.DataFrame(
    [
      s.to_dict(False)
      for s in sorted(students, key=(lambda s: s.sis_id))
    ],
    columns = headers)
  print(df["score"].describe())
  df.to_csv("output.csv")
  df[["score", "id"]].to_csv(os.path.join(os.path.dirname(CSV_FILE), "output.csv"))
  
  df["filename"] = df["name"].apply(lambda n: f"{'_'.join(n.split()[-1:] + n.split()[:-1])}.txt" )

  if os.path.exists(FEEDBACK_DIR):
    shutil.rmtree(FEEDBACK_DIR)
  os.mkdir(FEEDBACK_DIR)
  for index, row in df.iterrows():
    with open(os.path.join(FEEDBACK_DIR, row["filename"]), 'w') as fid:
      fid.write(getFeedback(questions, row))


if __name__ == "__main__":
  main()