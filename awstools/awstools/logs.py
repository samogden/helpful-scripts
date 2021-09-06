#!env python

import pandas as pd

def parse_log_event(log_msg):
  msg_split = log_msg.split('\t')
    
  msg_contents = {
    field.split(':')[0] : field.split(':')[1].strip()
    for field in msg_split
    if field.strip() != ''
  }
  df = pd.DataFrame([msg_contents])
  for col_name in df.columns:
    if "Duration" in col_name:
      df[col_name] = pd.to_timedelta(df[col_name]).dt.total_seconds()
  return df  

