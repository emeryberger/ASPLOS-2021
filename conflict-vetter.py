# conflict-vetter.py: finds all stated conflicts from authors and mails them for vetting to reviewers
#   - used for checking for bogus conflicts / conflict engineering.
# Author: Emery Berger <emery.berger@gmail.com>
# Released into the public domain.

# You will probably need to install bcrypt:
#   % python3 -m pip install bcrypt

# To use this script for your conference, you first need to download the following files from HotCRP:
#   confname-pcinfo.csv
#      go to https://confname.hotcrp.com/users?t=pc
#      scroll to the bottom, select all, click download, and choose "PC info".
#   confname-authors.csv
#      go to https://confname.hotcrp.com/search?q=&t=s
#      scroll to the bottom, select all, click download, and choose "Authors".
#   confname-pcconflicts.csv
#      go to https://confname.hotcrp.com/search?q=&t=s
#      scroll to the bottom, select all, click download, and choose "PC conflicts".

# You need to the run the script with a number of options, specified at the command line.
# The command will look something like this:
#
#   % python3 conflict-vetter.py --conference asplos21 --hashcode hellokitty --your-name "Emery Berger" --your-email "emery.berger@gmail.com" --your-password goodbyedoggy --form-url "https://forms.gle/someform"
#
# If you are using 2FA for Google mail, you can generate an App Password for use here:
#    https://security.google.com/settings/security/apppasswords
#
# NOTE: this command will only actually send mail if you explicitly add the command-line option --really-send
#
# As a side effect, this command produces an output file uidmap.csv, which you can use to reverse-lookup
# paper numbers from uids.

import argparse
import bcrypt
import csv
import random
import smtplib
import sys
import time
from typing import Dict, List
from collections import defaultdict

parser = argparse.ArgumentParser("conflict-vetter")
parser.add_argument("--conference", help="conference name, as in asplos2021")
parser.add_argument("--hashcode", help="hash code, for obscuring paper IDs")
parser.add_argument("--your-name", help="your name goes here, for signing the emails.")
parser.add_argument(
    "--your-email", help="your email goes here, for sending the emails."
)
parser.add_argument(
    "--your-password", help="your password goes here, for sending the emails."
)
parser.add_argument("--form-url", help="URL for form to fill out (e.g., Google Form).")

parser.add_argument("--really-send", help="indicate this to actually send mails.")


args = parser.parse_args()

if not args.conference or not args.hashcode or not args.your_name:
    parser.print_help()
    sys.exit(-1)

if args.really_send:
    reallySendMail = True
else:
    reallySendMail = False

senderFirstName = args.your_name
senderName = args.your_name + " <" + args.your_email + ">"
sender = args.your_email
password = args.your_password

names = {}
with open(args.conference + "-pcinfo.csv", "r") as csvfile:
    reader = csv.DictReader(csvfile, delimiter=",")
    for row in reader:
        key = row["email"].lower()
        value = row["first"] + " " + row["last"]
        names[key] = value


# Now we build a list of authors for each paper.
# allAuthors[paper number] = list of authors (by name and e-mail)

allAuthors: Dict[str, List[str]] = defaultdict(list)

with open(args.conference + "-authors.csv", "r") as csvfile:
    reader = csv.DictReader(csvfile, delimiter=",")
    for row in reader:
        key = row["paper"]
        value = row["first"] + " " + row["last"] + " <" + row["email"] + ">"
        allAuthors[key].append(value)

#
# Now read in the conflicts.
# conflicts[e-mail] = everyone who is on a paper with a stated conflict with e-mail
#

conflicts = defaultdict(list)
conflict_types: Dict[str, Dict[str, str]] = defaultdict(lambda: defaultdict(str))

with open(args.conference + "-pcconflicts.csv", "r") as csvfile:
    reader = csv.DictReader(csvfile, delimiter=",")
    for row in reader:
        alist = list(set(allAuthors[row["paper"]]))
        # Filter out institutional conflicts.
        recipient_domain = row["email"].split("@")[1]
        if row["conflicttype"] not in ["Pinned conflict", "Personal", "Other"]:
            continue
        if recipient_domain in ["outlook.com", "yahoo.com", "gmail.com"]:
            pass
        else:
            try:
                if recipient_domain in list(
                    map(lambda name: name.split("<")[1].split("@")[1][:-1], alist)
                ):
                    continue
            except:
                pass
        conflicts[row["email"]].append((row["paper"], alist))
        conflict_types[row["email"]][row["paper"]] = row["conflicttype"]

# Shuffle paper order.
for k in conflicts:
    random.shuffle(conflicts[k])

# Now, we read in all authors.
# We can use this to add noise to the potential conflicts (currently disabled).

authorsList = []
with open(args.conference + "-authors.csv", "r") as csvfile:
    reader = csv.DictReader(csvfile, delimiter=",")
    for row in reader:
        key = row["first"] + " " + row["last"]
        value = row["email"]
        authorsList.append(value)

uidmap = open("uidmap.csv", "w")
uidmap.write("email,paper,uid\n")

if reallySendMail:
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.ehlo()
    server.starttls()
    server.login(sender, password)

s = sorted(conflicts.keys())
msg = ""
for (count, recipient) in enumerate(s, 1):
    if reallySendMail:
        time.sleep(1)  # To avoid Google throttling
    msg = "From: " + senderName + "\nSubject: Conflicts to vet: "
    if recipient.lower() in names:
        msg += names[recipient.lower()]
    else:
        msg += recipient
    msg += "\n\nHi,\n\n"
    msg += (
        "This mail contains a list of all papers for which you have been marked\nas a conflict. The actual paper numbers have been encrypted.\n\nPlease check each author list to verify that at least one of the authors for\neach paper looks like a legitimate conflict. IF NOT, please enter each one on this form:\n\n  "
        + args.form_url
        + ".\n\n"
    )
    # Not actually sampling from random authors right now.
    # r = random.sample(authorsList,5)
    c = conflicts[recipient]
    ind = 1
    for (paper_id, l) in c:
        # print("l = (" + str(l) + ")")
        key = recipient + args.hashcode + paper_id
        uid = bcrypt.hashpw(key.encode("utf8"), bcrypt.gensalt())
        reduced_uid = str(uid)[9:21]
        uidmap.write(recipient + "," + paper_id + "," + reduced_uid + "\n")
        msg += str(ind) + ". " + "(UID = " + reduced_uid + ") - "
        ctype = conflict_types[recipient][paper_id]
        if ctype == "Pinned conflict":
            ctype = "Auto-detected conflict (probably institutional)"
        msg += ctype + " : "
        i = 0
        for k in l:
            msg += str(k)
            i += 1
            if i != len(l):
                msg += ", "
        msg += "\n"
        ind += 1
    msg += "\n\nThanks,\n" + senderFirstName + "\n"
    text_msg = msg.encode("utf-8")
    if reallySendMail:
        print("Sending mail to " + recipient + "...")
        server.sendmail(sender, recipient, text_msg)
    else:
        print("not sending mail to " + recipient)
        print("(use --really-send to actually send mail)")
        print(text_msg)

if reallySendMail:
    server.quit()

uidmap.close()
