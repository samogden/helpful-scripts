#!env python

import re
import random 

def tex_escape(text):
  # from https://stackoverflow.com/questions/16259923/how-can-i-escape-latex-special-characters-inside-django-templates
  """
      :param text: a plain text message
      :return: the message escaped to appear correctly in LaTeX
  """
  conv = {
      '&': r'\&',
      '%': r'\%',
      '$': r'\$',
      '#': r'\#',
      '_': r'\_',
      '{': r'\{',
      '}': r'\}',
      '~': r'\textasciitilde{}',
      '^': r'\^{}',
      '\\': r'\textbackslash{}',
      '<': r'\textless{}',
      '>': r'\textgreater{}',
  }
  regex = re.compile('|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key = lambda item: - len(item))))
  return regex.sub(lambda match: conv[match.group()], text)

def indent(text, num_spaces):
  lines = []
  for i, line in enumerate(text.split('\n')):
    if i == 0:
      lines.append(line)
    else:
      lines.append(f"{' ' * num_spaces}{line}")
  return '\n'.join(lines).strip()

def process_enumeration(text):
  lines = []
  enumerating = False
  for i, line in enumerate(text.split('\n')):
    if (line.lower().startswith('a.')
        or line.lower().startswith('a)')):
      lines.append(f"\\begin{{enumerate}}[label=(\\alph*)]")
      enumerating = True
    if enumerating and len(line) > 0:
      lines.append(f"  \\item{{{line[2:].strip()}}}")
    else:
      lines.append(line)
  if enumerating:
    lines.append(f'\\end{{enumerate}}')
  
  return '\n'.join(lines)

def process_codeblocks(text):
  lines = []
  in_codeblock = False
  for i, line in enumerate(text.split('\n')):
    if line.startswith('```'):
      if not in_codeblock:
        in_codeblock = True
        lines.append('\\begin{verbatim}')
      else:
        in_codeblock = False
        lines.append('\\end{verbatim}')
      continue
    lines.append(line)
  
  return '\n'.join(lines)

def process(text):
  text = tex_escape(text)
  text = process_enumeration(text)
  text = process_codeblocks(text)
  text = indent(text, 4)
  return text


with open("from_students.md") as fid:
  lines = [l.strip() for l in fid.readlines()]

chunks = []
question = ""
answer = ""
reading_question = True
for line in lines:
  if line == "###":
    chunks.append((question, answer))
    question = ""
    answer = ""
    reading_question = True
    continue
  if line == "":
    continue
  if reading_question:
    if line.startswith("A: "):
      reading_question = False
    else:
      question += line
      question += '\n'
  if not reading_question:
    answer += line
    answer += '\n'

random.shuffle(chunks)

with open("review.tex", 'w') as fid:
  fid.write("\\documentclass{beamer}\n")
  fid.write("%Information to be included in the title page:\n")
  fid.write("\\title{Final Exam Review Questions}\n")
  fid.write("\\author{Fall 2022 CST334}\n")
  fid.write("\\date{\\today}\n")
  fid.write("\\usepackage{enumitem}")
  fid.write("\\begin{document}\n")
  fid.write("\\titlepage\n")
  
  
  
  for question, answer in chunks:
    fid.write(f"\\begin{{frame}}[fragile]\n")
    fid.write(f"  \\only<1>{{\\frametitle{{Question}}}}\n")
    fid.write(f"  \\only<2>{{\\frametitle{{Answer}}}}\n")
    fid.write(f"  \n")
    fid.write(f"  {process(question)}\n\n")
    fid.write(f"  \\vspace{{1cm}}\n")
    fid.write(f"  \\onslide<2>{{\n")
    fid.write(f"    {process(answer)}\n")
    fid.write(f"  }}\n")
    fid.write(f"\\end{{frame}}\n\n")
  
  fid.write("\\end{document}\n")
  