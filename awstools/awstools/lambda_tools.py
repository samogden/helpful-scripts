#!env python

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

import time
import base64

import boto3

from . import logs

def get_client():
  return boto3.client('lambda')

def invoke_function(lambda_client, function_name):
  ts = time.time()
  response = lambda_client.invoke(
    FunctionName=function_name,
    LogType="Tail" # includes log in response
  )
  te = time.time()
  
  parsed_log = logs.parse_log_event(base64.b64decode(response["LogResult"]).decode('utf-8'))
  
  return (te - ts), parsed_log
