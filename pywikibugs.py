#!/data/project/wikibugs/py34-base/bin/python3
import asyncio
import asyncio_redis
import email, email.policy
import glob
import os
import bzparser
import pprint
import subprocess

import logging.config
from irc3.plugins.command import command
import logging
import irc3

from config import irc_password
from channels import channels, default_channel, firehose_channel

import subprocess
try:
    __version__ = subprocess.Popen(["git", "describe"],
                                   cwd=os.path.split(__file__)[0],
                                   stdout=subprocess.PIPE
                  ).communicate()[0].decode('ascii').strip()
except Exception as e:
    __version__ = '2.0 (unknown subrevision)'


MAX_MESSAGE_LENGTH = 80*4

COLORS = {'white': 0, 'black': 1, 'blue': 2, 'green': 3, 'red': 4, 'brown': 5, 
          'purple': 6, 'orange': 7, 'yellow': 8, 'lime': 9, 'teal': 10,
          'cyan': 11, 'royal': 12, 'pink': 13, 'grey': 14, 'silver': 15}

def colorify(text, foreground=None, background=None):
    outtext = "\x03"
    if foreground:
        outtext += str(COLORS[foreground])
    if background:
        outtext += "," + str(COLORS[background])
    outtext += text
    outtext += "\x03"
    
    return outtext

@asyncio.coroutine
def parse_email(mail):
    bep = bzparser.BugzillaEmailParser(mail)
    bep.parse()
    
    fixup_future = asyncio.get_event_loop().run_in_executor(None, bep.fixup_real_name)
    
    # after 30 secs, give up retrieving the real name
    done = yield from asyncio.wait_for(fixup_future, timeout=30)
    
    return bep.result

def is_gerrit_change(parsed_email):
    return parsed_email["email"] == "gerritadmin@wikimedia.org"

def send_messages(bot, parsed_email):
    sent_once = False
    # first, build the message
    for channel, channel_conf in channels.items():
        # Works with just a lambda by default
        # You can pass additional options by making it a tuple
        if hasattr(channel_conf, '__call__'):
            filter = channel_conf
            params = {}
        else:
            filter, params = channel_conf
        if filter(parsed_email) and not is_gerrit_change(parsed_email):
            msg = build_message(parsed_email, **params)
            bot.privmsg(channel, msg)
            sent_once = True
    # If we didn't match any channel, send to the default one
    if not sent_once:
        msg = build_message(parsed_email)
        bot.privmsg(default_channel, msg)

    # Send to the firehose anyway
    msg = build_message(parsed_email)
    bot.privmsg(firehose_channel, msg)

    
def build_message(parsed_email, hide_product=False):
    cutoff_length = MAX_MESSAGE_LENGTH
    text = ""
    
    if not hide_product:
        text += colorify(parsed_email["X-Bugzilla-Product"], "green")
    if parsed_email["X-Bugzilla-Component"] != "General":
        text += " / " + colorify(parsed_email["X-Bugzilla-Component"], "green")
    text += ": "
    text += parsed_email["summary"] + " - "
    
    text += colorify(parsed_email.get("shorturltocomment", parsed_email["shorturl"]), "teal") + " "
    
    name = parsed_email.get("realname", None) or parsed_email["email"].split("@")[0]
    text += "(" + colorify(name, "teal") + ") "
    # the following is (semi-)optional and can be cut off if the message becomes too long
    # however, we want to keep the previous items
    cutoff_length = max(cutoff_length, len(text))
    
    # we want to show the following changes:
    # status/reso
    # prio/severity
    # assigned to
    
    if "changes" in parsed_email:
        c = parsed_email["changes"]
        
        if "Status" in c or "Resolution" in c:
            status_len = 3
            reso_len = 3
            
            sbefore = c.get("Status", {'removed': parsed_email["X-Bugzilla-Status"]})['removed'][:status_len]
            safter = c.get("Status", {'added': parsed_email["X-Bugzilla-Status"]})['added'][:status_len]
            
            if sbefore == "RESOLVED"[:status_len]:
                sbefore += "/" + c.get("Resolution", {'removed': "?"})['removed'][:reso_len]
            if safter == "RESOLVED"[:status_len]:
                safter += "/" + c.get("Resolution", {'added': "?"})['added'][:reso_len]
            
            if sbefore == "---":
                text += colorify(safter, "green")
            else:
                text += colorify(sbefore, "brown") + ">" + colorify(safter, "green")
                
            text += " "
            
        if "Priority" in c:
            prio_length = 6
            pr = c["Priority"]["removed"]
            pa = c["Priority"]["added"]
            
            text += "p:"
            if pr != "---":
                text += colorify(pr[:prio_length], 'brown') + ">"
            text += colorify(pa[:prio_length], 'green') + " "
            
        if "Severity" in c:
            sev_length = 6
            sr = c["Severity"]["removed"]
            sa = c["Severity"]["added"]
            
            text += "s:"
            if sr != "---":
                text += colorify(sr[:sev_length], 'brown') + ">"
            text += colorify(sa[:sev_length], 'green') + " "
            
        if "Assignee" in c:
            a = c["Assignee"]
            sr = a.get('removed_realname', None) or a["removed"].split("@")[0]
            sa = a.get('added_realname', None) or a['added'].split('@')[0]
         
            if a["removed"] in ["---", "wikibugs-l@lists.wikimedia.org", "Pywikipedia-bugs@lists.wikimedia.org", "jforrester+veteambztickets@wikimedia.org"]:
                sr = "None"
            if a["added"] in ["---", "wikibugs-l@lists.wikimedia.org", "Pywikipedia-bugs@lists.wikimedia.org", "jforrester+veteambztickets@wikimedia.org"]:
                sa = "None"
            
            text += "a:"
            if sr != "None":
                text += colorify(sr.split("@")[0], 'brown') + ">"
            text += colorify(sa.split("@")[0], 'green') + " "
           
 
    if "comment" in parsed_email:
        text += " ".join(parsed_email["comment"].split("\n"))
        
    # strip annoying stuff from the message
    text = text.replace("\t", " ")
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH-3].strip() + "..."
    
    return text
    
@asyncio.coroutine
def parse_reply(bot, reply):
    fn = "output/%06i" % len(glob.glob('output/*.raw'))
    open(fn + ".raw", 'wb').write(reply.value)
    try:
        parsed_email = yield from parse_email(reply.value)
        send_messages(bot, parsed_email)
        bot.log.info(pprint.pformat(parsed_email))
    except Exception as e:
        import traceback
        bot.log.critical(traceback.format_exc())

@asyncio.coroutine
def redisrunner(bot):
    while True:
        try:
            yield from redislistener(bot)
        except Exception as e:
            import traceback
            bot.log.critical(traceback.format_exc())
            bot.log.info("...restarting Redis listener in a few seconds.")
        yield from asyncio.sleep(5)
        
@asyncio.coroutine
def redislistener(bot):
    # Create connection
    connection = yield from asyncio_redis.Connection.create(
        host='tools-redis', port=6379,
        encoder=asyncio_redis.encoders.BytesEncoder()
    )

    # Create subscriber.
    subscriber = yield from connection.start_subscribe()

    # Subscribe to channel.
    yield from subscriber.subscribe([ b'wikibugs-l' ])
    bot.log.info("Subscribed to channels.")
    # Inside a while loop, wait for incoming events.
    while True:
        try:
            reply = yield from subscriber.next_published()
            asyncio.Task(parse_reply(bot, reply)) # do not wait for response
        except Exception as e:
            import traceback
            bot.log.critical(traceback.format_exc())
            yield from asyncio.sleep(1)
            

if __name__ == '__main__':
    # logging configuration
    logdict = irc3.config.LOGGING.copy()
    for k,v in logdict['formatters'].items():
        v['format'] = '%(asctime)s ' + v['format']
    logging.config.dictConfig(logdict)

    channels_list = list(channels.keys())
    channels_list.append(default_channel)
    channels_list.append(firehose_channel)

    # instanciate a bot
    bot = irc3.IrcBot(
        nick='wikibugs', autojoins=channels_list,
        host='irc.freenode.net', port=7000, ssl=True,
        password=irc_password,
        realname="pywikibugs2",
        userinfo="Wikibugs v2.0, https://tools.wmflabs.org/wikibugs/",
        url="https://tools.wmflabs.org/wikibugs/",
        includes=[
            'irc3.plugins.core',
            'irc3.plugins.ctcp',
            __name__,  # this register MyPlugin
        ],
        verbose=True,
        ctcp={'version': 'pywikibugs %s running on irc3 {version}. See {url} for more details.' % __version__,
              'userinfo': '{userinfo}',
              'ping': 'PONG'}
    )

    asyncio.Task(redisrunner(bot))
    bot.run()
    
