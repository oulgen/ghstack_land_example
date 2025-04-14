#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import subprocess
import sys

import requests
import time



def main():
    gh = requests.Session()
    gh.headers.update(
        {
            "Authorization": f'Bearer {os.environ["GITHUB_TOKEN"]}',
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    NUMBER, head_ref, REPO = int(sys.argv[1]), sys.argv[2], sys.argv[3]

    def must(cond, msg):
        if not cond:
            print(msg)
            gh.post(
                f"https://api.github.com/repos/{REPO}/issues/{NUMBER}/comments",
                json={
                    "body": f"ghstack bot failed: {msg}",
                },
            )
            exit(1)

    print(head_ref)
    must(
        head_ref and re.match(r"^gh/[A-Za-z0-9-]+/[0-9]+/head$", head_ref),
        "Not a ghstack PR",
    )
    orig_ref = head_ref.replace("/head", "/orig")
    print(":: Fetching newest main...")
    must(os.system("git fetch origin main") == 0, "Can't fetch main")
    print(":: Fetching orig branch...")
    must(os.system(f"git fetch origin {orig_ref}") == 0, "Can't fetch orig branch")

    proc = subprocess.Popen(
        "git log FETCH_HEAD...$(git merge-base FETCH_HEAD origin/main)",
        stdout=subprocess.PIPE,
        shell=True,
    )
    out, _ = proc.communicate()
    must(proc.wait() == 0, "`git log` command failed!")

    pr_numbers = re.findall(
        r"Pull Request resolved: https://github.com/.*?/pull/([0-9]+)",
        out.decode("utf-8"),
    )
    pr_numbers = list(map(int, pr_numbers))
    print(pr_numbers)
    must(pr_numbers and pr_numbers[0] == NUMBER, "Extracted PR numbers not seems right!")
    
    for n in pr_numbers:
        print(f":: Checking PR status #{n}... ", end="")
        
        # Get PR object with mergeable state
        resp = gh.get(
            f"https://api.github.com/repos/{REPO}/pulls/{n}",
            headers={"Accept": "application/vnd.github.v3+json"}
        )
        must(resp.ok, f"Error getting PR #{n}!")
        pr_obj = resp.json()
        
        # Check if GitHub is still calculating the mergeable state
        mergeable_state = pr_obj.get("mergeable_state", "unknown")
        if mergeable_state == "unknown":
            # Wait and try again - GitHub is still calculating
            time.sleep(2)
            resp = gh.get(
                f"https://api.github.com/repos/{REPO}/pulls/{n}",
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            must(resp.ok, f"Error getting PR #{n} on retry!")
            pr_obj = resp.json()
            mergeable_state = pr_obj.get("mergeable_state", "unknown")
        
        # Check mergeable state
        must(
            mergeable_state != "blocked", 
            f"PR #{n} is blocked from merging (possibly failing status checks)!"
        )
        must(
            mergeable_state != "dirty", 
            f"PR #{n} has merge conflicts that need to be resolved!"
        )
        must(
            mergeable_state != "unstable", 
            f"PR #{n} has failing or pending required status checks!"
        )
        must(
            mergeable_state == "clean", 
            f"PR #{n} is not ready to merge (state: {mergeable_state})!"
        )
        
        # If you still want to verify approval status specifically
        resp = gh.get(f"https://api.github.com/repos/{REPO}/pulls/{n}/reviews")
        must(resp.ok, f"Error getting reviews for PR #{n}!")
        reviews = resp.json()
        
        # Check if at least one approval exists
        has_approval = any(review["state"] == "APPROVED" for review in reviews)
        must(has_approval, f"PR #{n} has no approvals!")
        
        print("SUCCESS!")

    print(":: All PRs are ready to be landed!")


if __name__ == "__main__":
    main()