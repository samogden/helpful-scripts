#!env python

import io

import boto3

def get_client():
  return boto3.client('s3')

def get_file_obj(bucket_name, file_name, *args, **kwargs):
  if "client" in kwargs:
    client = kwargs["client"]
  else:
    client = get_client()
  
  data_stream = io.BytesIO()
  client.download_fileobj(bucket_name, 
                            file_name,
                            data_stream)
  data_stream.seek(0)
  return data_stream
