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
#    parser.add_argument('-b', '--batch', type=int, help='Batch Number')
#    parser.add_argument('-c', '--case_num', type=str, help='Case Number')
    parser.add_argument('-v', '--verbose', action="store_true", help='Verbose mode will print out more information')
    parser.add_argument("--dryrun", action="store_true", help='dryrun')
### 
    parser.add_argument('-e', '--end_num', type=str, help='Ending Case Number', default = "YSC1790190000")
    parser.add_argument('-r', '--range', type=int, help='Search Range', default = 20000)
    parser.add_argument('-i', '--interval', type=int, help='Search Interval', default = 500)
    parser.add_argument('-k', '--skip', type=int, help='Sample Interval', default = 1)
###
    return parser.parse_args()

def get_result(case_num,prefix,verbose):
    retries = 0
    while True:
        info = {}
        result=''
        url = 'https://egov.uscis.gov/casestatus/mycasestatus.do'
        case_num = prefix + str(case_num)
        print "case_num: ", case_num
        response = requests.post(url, data={"appReceiptNum": case_num})
        if response.status_code != 200:
            print "USCIS format is incorrect"
            time.sleep(120) 
            retries += 1
            continue    
            
        soup = BeautifulSoup(response.content)
        mycase_txt = soup.findAll("div", { "class" : "current-status-sec" })

        for i in mycase_txt:
            result = i.get_text() 
            if "Your Current Status" in status:
                status = status.replace("Your Current Status:", "").strip("\n\r\t+ ")
                info[case_num] = {}
                return info

        if retries < 2:
            print "USCIS format is incorrect"
            time.sleep(120) 
            retries += 1
        else:
            print "retry too many times, exiting"
            print soup
            sys.exit()

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

    now = datetime.datetime.now()
    result_file = open('data-%s-%s-%s.yml' % (str(overall_start), str(overall_end), now.strftime("%m-%d")), 'w') 
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
        print "start_num: %d, recv_case_num: %d, recv_rate: %.2f%%" % (start, recv_case_num, 100.0 * recv_case_num / total_case_num)
        result_file.write("start_num: %d, recv_rate: %.2f%%" % (start, 100.0 * recv_case_num / total_case_num))

        json_type = json.dumps(final_result,indent=4)
        with open('result/data-%s-%s-%s.yml' % (str(start), str(end), now.strftime("%m-%d")), 'w') as outfile:
            yaml.dump(yaml.load(json_type), outfile, allow_unicode=True)

if __name__ == "__main__":
    main()
