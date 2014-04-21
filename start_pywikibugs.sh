#!/bin/bash
jstop pywikibugs
sleep 1
jstart -mem 1G -once /data/project/wikibugs/src/pywikibugs/pywikibugs.py
