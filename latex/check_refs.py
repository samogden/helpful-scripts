#!env python

import sys
import re
import glob
import argparse
import logging
import collections

## https://www.bibme.org/


def getParser(add_help=True, include_parents=True):
  parser = argparse.ArgumentParser(add_help=add_help)
  
  parser.add_argument('--tex_dir', default='.', help='Path to tex directory')
  parser.add_argument('--exclude_dir', default=[], nargs='+', help="Paths to ignore")
  
  parser.add_argument('--path_to_bib', default='bib.bib', help='Path to bibliography file')
  parser.add_argument('--keys_to_ignore', default=[], nargs='+', help="keys to ignore (e.g. 'our-repo')")
  
  return parser

def main():
  flags = getParser().parse_args()
  
  
  cited_already = getCitedFromBib(flags.path_to_bib)
  files_by_citation = collections.defaultdict(list)
  
  files_to_check = glob.glob(f'{flags.tex_dir}/**/*.tex', recursive=True)
  files_to_check = list(filter( (lambda f: not any([ex in f for ex in flags.exclude_dir])), files_to_check))
  
  for f in files_to_check:
    citations = getCitationsFromFile(f)
    #if len(citations) > 0:
    #  logging.info(f"{f} : {citations}")
    for c in citations:
      files_by_citation[c].append(f)
  
  print("")
  for (c, f) in sorted(files_by_citation.items(), key=(lambda t: t[0])):
    if c in cited_already:
      continue
    if c in flags.keys_to_ignore:
      continue
    print(f"{c}:\t{' '.join(f)}")
  print("")

def getCitationsFromFile(f):
  pattern = r'\\cite{([^}]*)}'
  with open(f) as fid:
    lines = fid.readlines()
  ls = re.findall(pattern, ''.join(filter((lambda l: not l.startswith('%')), lines)))
  #logging.debug(f"{f} : {ls}")
  if len(ls) == 0:
    return []
  citations = list(set([s.strip() for s in ','.join(list(ls)).split(',')]))
  return citations

def getCitedFromBib(b):
  #pattern = re.compile(r'^\s@[^{}]*{([^,]*),', re.DOTALL)
  pattern = re.compile(r'@.*{(.*),')
  with open(b) as fid:
    lines = fid.readlines()
  ls = re.findall(pattern, ''.join(lines))
  logging.debug(ls)
  return list(ls)
  
  

if __name__ == '__main__':
  logging.getLogger().setLevel(logging.DEBUG)
  main()

