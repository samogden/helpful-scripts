#!env python

import argparse
import types
import os

import pandas as pd

def parse_flags():
  parser = argparse.ArgumentParser()

  parser.add_argument("--csv_file", required=True, help="The CSV file to update a column into")
  parser.add_argument("--overwrite_orig", action="store_true", help="If true, overwrites original csv file.")
  parser.add_argument("--col_name", required=True, help="Name of column to reformat")
  parser.add_argument("--cutoff", type=float, default=2.5, help="Cut off for whether something is 0 or 1")
  parser.add_argument("--invert", action="store_true", help="Switches if things are 0 or 1")

  args = parser.parse_args()
  return args

def load_csv(input_file):
  df = pd.read_csv(input_file)
  return df

def change_column(df: pd.DataFrame, col_name: str, replacement_func):
  df[col_name] = df[col_name].apply(replacement_func)
  return df

def save_csv(df: pd.DataFrame, output_file: str):
  df.to_csv(output_file, index=False)

def main():

  # Parse arguments
  args = parse_flags()

  # Set things up
  ## Set up function to use for filtering
  def filter_func(val):
    # There's a more elegant way to do this but my brain isn't braining right now
    if val < args.cutoff:
      return 0 if not args.invert else 1
    else:
      return 1 if not args.invert else 0

  ## Set up output file
  if args.overwrite_orig:
    output_file_name = args.csv_file
  else:
    if not os.path.exists("output"):
      os.mkdir("output")
    output_file_name = os.path.join("output", args.csv_file)

  # Do things
  df = load_csv(args.csv_file)
  change_column(df, args.col_name, filter_func)
  save_csv(df, output_file_name)


if __name__ == "__main__":
  main()
