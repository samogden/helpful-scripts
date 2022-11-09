#!env python

import argparse

import logging
import os.path
import zipfile
import xml.etree.ElementTree
import collections
import datetime

logging.basicConfig()
log = logging.getLogger(__file__)
log.setLevel(logging.DEBUG)

def get_assignment_dates(input_file) -> dict[datetime.datetime, list[str]] | None:
  if not zipfile.is_zipfile(input_file):
    return None
  assignments_by_date = collections.defaultdict(list)
  z = zipfile.ZipFile(input_file)
  for f in z.filelist:
    log.debug(f)
    if "assessment_meta.xml" in f.filename:
      ns = []
      with z.open(f, 'r') as zfid:
        tree = xml.etree.ElementTree.parse(zfid)
        root = tree.getroot()
        assignment_name = None
        assignment_duedate = None
        for child in root:
          if "title" in child.tag:
            log.debug(f"child: {child} -> {child.text}")
            assignment_name = child.text
          elif "due_at" in child.tag:
            log.debug(f"child: {child} -> {child.text}")
            assignment_duedate = datetime.datetime.strptime(
              child.text,
              "%Y-%m-%dT%H:%M:%S"
            )
          else:
            pass
            #log.debug(f"child: {child}")
        if (assignment_name is not None) and (assignment_duedate is not None):
          assignments_by_date[assignment_duedate].append(assignment_name)
  return assignments_by_date

def parse_flags():
  parser = argparse.ArgumentParser()
  parser.add_argument("--input_dir", default=None)
  parser.add_argument(
    "--input_file",
    default=os.path.expanduser("~/Downloads/cst311-01-02-fa22-meta-intro-to-computer-networks-export.imscc")
  )
  return parser.parse_args()
  
def main():
  flags = parse_flags()
  assignments_by_date = get_assignment_dates(flags.input_file)
  for date in sorted(assignments_by_date.keys()):
    print(f"{date.strftime('%c')} : {assignments_by_date[date]}")

if __name__ == "__main__":
  main()