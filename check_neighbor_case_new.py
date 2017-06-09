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
import sys
import argparse
import json
import yaml
import datetime
import time
import multiprocessing
from multiprocessing import Value, Lock, Manager
from bs4 import BeautifulSoup
import certifi

CPU_CORES = multiprocessing.cpu_count()
RETRY_THRESHOLD1 = 3
RETRY_THRESHOLD2 = 6

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
    url = 'https://egov.uscis.gov/casestatus/mycasestatus.do'
    case_num = prefix + str(case_num)
    if verbose:
        print "case_num: ", case_num

    while True:
        info = {}
        result=''
        response = requests.post(url, data={"appReceiptNum": case_num})
        if response.status_code == 200:
            soup = BeautifulSoup(response.content)
            mycase_txt = soup.findAll("div", { "class" : "current-status-sec" })

            for i in mycase_txt:
                result = i.get_text() 
                if "Your Current Status" in result:
                    result = result.replace("Your Current Status:", "").strip("\n\r\t+ ")
                    info[case_num] = {}
                    info[case_num]["Status"] = result
                    return info

        if retries < RETRY_THRESHOLD1:
            print "USCIS format is incorrect: retry after 15 secs"
            time.sleep(15) 
            retries += 1
        elif retries < RETRY_THRESHOLD2:
            print "USCIS format is incorrect: possible IP ban, retry after 300 secs"
            time.sleep(300) 
            retries += 1
        else:
            print "retried too many times, printing website content and exiting"
            print soup
            sys.exit()

def get_batch_pair(interval,case_s,case_e,skip):
    batch = {}
    info = []
    per_cpu = (interval + CPU_CORES - 1) / CPU_CORES
    for i in range(CPU_CORES - 1):
        batch = {
          "start": case_s + i * per_cpu,
          "end": case_s + (i + 1) * per_cpu,
          "skip": skip
        }
        info.append(batch)
    info.append({"start": case_s + (CPU_CORES - 1) * per_cpu, "end": case_e, "skip": skip})
    return info

def query_website(ns,batch_result,prefix,lock,verbose):
    local_result = []
    if verbose:
        print "start is %d, end is %d"%(int(batch_result['start']),int(batch_result['end']))
        print "current pid: ", multiprocessing.current_process()
    for case_n in range(int(batch_result['start']),int(batch_result['end']), int(batch_result['skip'])):
        local_result.append(get_result(case_n,prefix,verbose))

    ## local_result: list of dicts. Each dict contains one case_num
    lock.acquire()
    ns.df = ns.df + local_result
    lock.release()

def main():
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
    result_file = open('data-%s-%s-%s.log' % (str(overall_start), str(overall_end), now.strftime("%m-%d")), 'w', 0) 
        # 0 is buffer size. This means the content will be flushed to file instantly. 

    for start in range(overall_start, overall_end, interval):
        end = start + interval
        final_result = []

        if (interval / skip) > (CPU_CORES * 5):
            lock = Lock()
            jobs = []
            mgr = Manager()
            ns = mgr.Namespace()
    
            ns.df = final_result
            batch_result = get_batch_pair(interval,start,end,skip)

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
        mailed_case_num = 0
        for result_dict in final_result:              ## dict:{case_num: {type, status, recv} 
            for key in result_dict.values(): 
                if key['Status'][:15] == "Card Was Mailed":
                    mailed_case_num += 1
                total_case_num += 1

        if total_case_num == 0:
            continue
        print "start_num: %d, mailed_case_num: %d, mailed_rate: %.0f%%" % (start, mailed_case_num, 100.0 * mailed_case_num / total_case_num)
        result_file.write("start_num: %d, mailed_rate: %.0f%%\n" % (start, 100.0 * mailed_case_num / total_case_num))

        json_type = json.dumps(final_result,indent=4)
        with open('result/data-%s-%s-%s.yml' % (str(start), str(end), now.strftime("%m-%d")), 'w') as outfile:
            yaml.dump(yaml.load(json_type), outfile, allow_unicode=True)

if __name__ == "__main__":
    main()
