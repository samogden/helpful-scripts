from setuptools import setup

setup(
  name='awstools',
  version='0.0.1',
  author='Samuel S. Ogden',
  author_email='Samuel.S.Ogden@gmail.com',
  packages=['awstools'],
  #scripts=['bin/script1','bin/script2'],
  #url='http://pypi.python.org/pypi/PackageName/',
  #license='LICENSE.txt',
  #description='An awesome package that does something',
  #long_description=open('README.txt').read(),
  install_requires=[
    "boto3",
    "pandas"
  ],
)