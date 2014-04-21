#!/usr/bin/env python
import sys
import redis
import argparse

parser = argparse.ArgumentParser(
    description='Pushes data from stdin to redis channels'
)

parser.add_argument('channels',
                    metavar='channel', nargs='+',
                    help='the channels/lists to publish the data on')

parser.add_argument('--host',
                    dest='host', default='tools-redis',
                    help='the host name of the redis server')

parser.add_argument('--port',
                    dest='port', type=int, default=6379,
                    help='the port number of the redis server')

parser.add_argument('--method',
                    dest='method', default='publish',
                    choices=['append', 'lpush', 'lpushx', 'rpush', 'rpushx',
                             'sadd', 'pfadd', 'publish'],
                    help="method used to store data. See redis docs for "
                         "details. rpush (add to the end of a list) and "
                         "publish (send to subscribers) are most useful. "
                         "Default is 'publish'.")

args = parser.parse_args()

# Redis does not support streaming binary data, so we have to fully
# read the input.
data = sys.stdin.read()

r = redis.Redis(host=args.host, port=args.port)
method = getattr(r, args.method)

for channel in args.channels:
    method(channel, data)
