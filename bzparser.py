import email
import email.policy
import re
import xmlrpc.client
import glob

# Monkey patch email parser to work around crappy bugzilla emails
# (=?... is only allowed after whitespace)
from get_unstructured import get_unstructured

import email._header_value_parser
import email.headerregistry
email.headerregistry.UnstructuredHeader.value_parser = staticmethod(get_unstructured)


class ParseError(Exception):
    pass

nameemailmatcher = r"""
(
    (?P<realname>.*?)\ \<(?P<email>.*@.*)\> # Bryan Davis <bdavis@wikimedia.org>
|
    (?P<email2>.*@.*)                       # ryasmeen@wikimedia.org
)
"""


class BugzillaEmailParser():
    def __init__(self, email):
        self.email = email
        self.result = {}

    def parse(self):
        m = email.message_from_bytes(self.email, policy=email.policy.strict)
        self.parse_headers(m)
        self.result["email"] = self.result["X-Bugzilla-Who"]
        self.result["summary"] = self.result["Subject"].split("]", 1)[1].strip()

        content = m.get_body().get_content()
        content = content.split("\n\n-- \nYou are receiving this mail because:")[0]

        self.parse_email(content)

        if 'changes' in self.result and 'Summary' in self.result["changes"]:
            self.result["summary"] = self.result["changes"]["Summary"]["added"]

    def fixup_real_name(self):
        if 'realname' not in self.result or not self.result['realname']:
            self.result['realname'] = self.trygetname(self.result['email'])

        if 'changes' in self.result and 'Assignee' in self.result['changes']:
            a = self.result['changes']['Assignee']
            a['removed'] = a['removed'].replace(' ', '')  # fixup spaces in email addresses due to crappy parsing
            a['added'] = a['added'].replace(' ', '')
            a['removed_realname'] = self.trygetname(a['removed'])
            a['added_realname'] = self.trygetname(a['added'])

    def trygetname(self, email):
        try:
            bzproxy = xmlrpc.client.ServerProxy('https://bugzilla.wikimedia.org/xmlrpc.cgi')
            bzuser = bzproxy.User.get({'names': email})
            return bzuser['users'][0]['real_name']
        except (xmlrpc.client.Fault, KeyError):
            return None

    def parse_headers(self, m):
        for header, value in m.items():
            if header.startswith('X-Bugzilla-') or \
               header in ["Subject", "Date"]:
                self.result[header] = str(value)

    def parse_email(self, text):
        lines = text.split("\n")

        # incrementally parse the e-mail
        self.result['url'] = lines.pop(0)
        self.result["shorturl"] = self.result["url"].replace("show_bug.cgi?id=", "")
        assert(lines.pop(0) == "")

        if self.result['X-Bugzilla-Type'] == 'new':
            self.parse_new_email(lines)
        elif self.result['X-Bugzilla-Type'] == 'changed':
            self.parse_change_email(lines)

        assert(not lines)

    def parse_new_email(self, lines):
        self.result["changes"] = {}

        # we use the Bug ID line (the first one) to get the : position
        colon_pos = lines.pop(0).index(':')

        oldwhat = None
        while True:
            line = lines.pop(0)
            if line == "":
                break

            what, value = line[:colon_pos], line[colon_pos + 1:]
            what = what.strip()
            value = value.strip()

            if what == "Bug ID":
                continue
            elif what != "":
                oldwhat = what
                self.result["changes"][what] = {'removed': '---', 'added': value}
            else:
                if value:
                    self.result["changes"][oldwhat]['added'] += " " + value

        self.result["commentnumber"] = 0
        self.result["comment"] = ''
        while(lines):
            line = lines.pop(0)
            self.result["comment"] += line + '\n'

    def parse_change_email(self, lines):
        self.remove_dependency_note(lines)
        self.try_parse_change_header(lines)
        self.try_parse_changes(lines)
        self.try_parse_comment(lines)

    def remove_dependency_note(self, lines):
        if re.match(r"^Bug \d+ depends on bug \d+, which changed state\.$", lines[0]):
            lines.pop(0)
            assert(lines.pop(0) == "")
            while True:
                line = lines.pop(0)
                if line == "":
                    break

    def try_parse_change_header(self, lines):
        changed_by_line = re.match(r"^" + nameemailmatcher + "\ changed:$",
                                   lines[0],
                                   re.UNICODE | re.VERBOSE
                                   )

        if not changed_by_line:
            return

        lines.pop(0)
        self.result['realname'] = changed_by_line.group('realname')
        self.result['email'] = changed_by_line.group('email') or changed_by_line.group('email2')

        assert(lines.pop(0) == "")

    def try_parse_changes(self, lines):
        if not re.match(r"^ *What *\| *Removed *\|Added *$", lines[0]):
            return

        # now we need to parse the changes table.
        lw, lr, la = [len(x) for x in lines.pop(0).split('|', 2)]
        iwb = 0
        iwe = iwb + lw
        irb = iwe + 1
        ire = irb + lr
        iab = ire + 1

        assert(lines.pop(0) == "----------------------------------------------------------------------------")

        self.result['changes'] = {}

        oldwhat = None
        while(lines):
            line = lines.pop(0)
            if line == "":
                break
            what = line[iwb:iwe].strip()
            rem = line[irb:ire].strip()
            add = line[iab:].strip()

            if what:
                oldwhat = what
                self.result['changes'][what] = {'removed': rem, 'added': add}
            else:
                if rem:
                    self.result['changes'][oldwhat]['removed'] += " " + rem
                if add:
                    self.result['changes'][oldwhat]['added'] += " " + add

    def try_parse_comment(self, lines):
        if not lines:
            return
        comment_by_line = re.match(r"^---\ Comment\ \#(?P<commentnumber>\d+)\ from\ " + nameemailmatcher + r"\ ---$",
                                   lines[0],
                                   re.UNICODE | re.VERBOSE
                                   )

        if not comment_by_line:
            return

        lines.pop(0)
        self.result['realname'] = self.result.get('realname', None) or comment_by_line.group('realname')
        self.result['email'] = self.result.get('email', None) or comment_by_line.group('email') or comment_by_line('email2')
        self.result['commentnumber'] = int(comment_by_line.group('commentnumber'))
        self.result['shorturltocomment'] = self.result['shorturl'] + "#c" + str(self.result['commentnumber'])

        self.result['comment'] = ''
        while(lines):
            line = lines.pop(0)
            self.result["comment"] += line + '\n'

if __name__ == "__main__":
    for fn in sorted(glob.glob("000359.raw")):
        print(fn)
        b = BugzillaEmailParser(open(fn, 'rb').read())
        b.parse()
        print(b.result)
