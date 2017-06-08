#!/usr/bin/env python

# Copyright (c) 2017, George Haoran Wang georgewhr@gmail.com
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import requests
import re
import sys
import os
import pycurl, json
import cStringIO
import argparse
import json
import yaml
import datetime
import time
import multiprocessing
import io
from multiprocessing import Value, Lock, Manager
from tabulate import tabulate
from bs4 import BeautifulSoup
import certifi

CPU_CORES = multiprocessing.cpu_count()

def cmdArgumentParser():
  parser = argparse.ArgumentParser()
### 
  parser.add_argument('-b', '--batch', type=int, help='Batch Number')
  parser.add_argument('-c', '--case_num', type=str, help='Case Number')
  parser.add_argument('-v', '--verbose', action="store_true", help='Verbose mode will print out more information')
  parser.add_argument("--dryrun", action="store_true", help='dryrun')
### 
  parser.add_argument('-e', '--end_num', type=str, help='Ending Case Number', default = "YSC1800000000")
# parser.add_argument('-r', '--range', type=int, help='Search Range', default = 20000000)
  parser.add_argument('-r', '--range', type=int, help='Search Range', default = 100000)
  parser.add_argument('-i', '--interval', type=int, help='Search Interval', default = 100000)
  parser.add_argument('-s', '--skip', type=int, help='Skip Interval (Sample)', default = 500)
###
  return parser.parse_args()

def get_result(case_num,prefix,verbose):
  info = {}
  result=''
  buf = cStringIO.StringIO()
  url = 'https://egov.uscis.gov/casestatus/mycasestatus.do'
  case_num = prefix + str(case_num)
  c = pycurl.Curl()
  c.setopt(c.URL, url)
  c.setopt(c.POSTFIELDS, 'appReceiptNum=%s'%case_num)
  c.setopt(c.WRITEFUNCTION, buf.write)
  c.setopt(c.CAINFO, certifi.where())
  c.perform()

  soup = BeautifulSoup(buf.getvalue(),"html.parser")
  mycase_txt = soup.findAll("div", { "class" : "rows text-center" })

  for i in mycase_txt:
    result=result+i.text

  result = result.split('\n')
  buf.close()
  try:
    details = result[2].split(',')
    recv_date = get_case_receive_date(details)
    case_type = get_case_type(result[2])
    info[case_num] = {}
    info[case_num]['Type'] = case_type
    info[case_num]['Status'] = result[1]
    info[case_num]['Received'] = recv_date

    if verbose:
      print info

  except Exception as e:
    print 'USCIS format is incorrect'
    print result
    sys.exit()

  return info

def get_batch_pair(interval,case_s,case_e):
  batch = {}
  info = []
  for i in range(interval / CPU_CORES):
    s = CPU_CORES * i + case_s
    e = s + CPU_CORES - 1
    batch = {
      "start":s,
      "end": e
    }
    info.append(batch)
  return info

def query_website(ns,batch_result,prefix,lock,verbose):
  local_result = []
  if verbose:
    print 's is %d, e is %d'%(int(batch_result['start']),int(batch_result['end']))
  for case_n in range(int(batch_result['start']),int(batch_result['end'])):
    local_result.append(get_result(case_n,prefix,verbose))

  ## local_result: list of dicts. Each dict contains one case_num
  lock.acquire()
  ns.df = ns.df + local_result
  lock.release()
  time.sleep(1)

def get_case_type(line):

  iCase = re.search("\w*I-\w*", line)
  crCase = re.search("\w*CR-\w*", line)
  irCase = re.search("\w*IR-\w*", line)
  
  if iCase:
    return iCase.group(0)
  elif crCase:
    return crCase.group(0)
  elif irCase:
    return irCase.group(0)
  else:
    return 'None Case'

def get_case_receive_date(details):
  year = str(details[1][1:])

  if year.isdigit():
    recv_date = details[0][3:] + ' ' + details[1][1:]
  else:
    recv_date = None

  return recv_date

def main():
  lock = Lock()
  jobs = []
  mgr = Manager()
  ns = mgr.Namespace()
  
  args = cmdArgumentParser()
  case_numberic = int(args.end_num[3:])
  prefix = args.end_num[:3]
  if not args.dryrun:
      overall_start = case_numberic - args.range
      overall_end = case_numberic
      interval = args.interval
      skip = args.skip
  else:
      overall_start = case_numberic - 500
      overall_end = case_numberic
      interval = 100
      skip = 25

  for start in range(overall_start, overall_end, interval):
    final_result = []
    ns.df = final_result

    rmnder = interval % CPU_CORES
    end = start + interval

    if False:
      batch_result = get_batch_pair(interval,start,end)

      for i in range(len(batch_result)):
        p = multiprocessing.Process(target=query_website,args=(ns,batch_result[i],prefix,lock,args.verbose,))
        jobs.append(p)
        p.start()
      for job in jobs:
        job.join()

      final_result = ns.df

    else:
      for i in range(start,end,skip):
        final_result.append(get_result(i,prefix,args.verbose))

    ## parse
    total_case_num = 0
    recv_case_num = 0
    for result_dict in final_result:              ## dict:{case_num: {type, status, recv} 
      for key in result_dict.values(): 
          if key['Status'][:15] == "Card Was Mailed":
              recv_case_num += 1
          total_case_num += 1

    if total_case_num == 0:
        continue
    print "start_num: %d, recv_rate: %.2f%%" % (start, 100.0 * recv_case_num / total_case_num)

    json_type = json.dumps(final_result,indent=4)
    now = datetime.datetime.now()
    with open('result/data-%s.yml'%now.strftime("%Y-%m-%d-%H-%M-%S"), 'w') as outfile:
      yaml.dump(yaml.load(json_type), outfile, allow_unicode=True)
  # print yaml.dump(yaml.load(json_type), allow_unicode=True)

if __name__ == "__main__":
  main()
