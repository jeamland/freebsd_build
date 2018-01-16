#!/usr/bin/env python3

import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument('-n', '--maxcount', type=int, metavar='count', help='Maximum number of bytes per line')
parser.add_argument('-s', '--pretty', action='store_true', help='Be more style(9) compliant')
parser.add_argument('-x', '--hex', action='store_true', help='Print hexadecimal numbers')
parser.add_argument('prefix', nargs='?', default='')
parser.add_argument('suffix', nargs='?', default='')
args = parser.parse_args()

sys.stdout.write(f'{args.prefix}\n')

count = linepos = 0
maxcount = args.maxcount or 0

for byte in sys.stdin.buffer.read():
    if count:
        linepos += sys.stdout.write(',')

    if (maxcount == 0 and linepos > 70) or (maxcount > 0 and count >= maxcount):
        sys.stdout.write('\n')
        count = linepos = 0

    if args.pretty:
        if count:
            linepos += sys.stdout.write(' ')
        else:
            sys.stdout.write('\t')
            linepos += 8

    if args.hex:
        linepos += sys.stdout.write(f'0x{byte:02x}')
    else:
        linepos += sys.stdout.write(f'{byte:d}')
    
    count += 1

sys.stdout.write('\n')
if args.suffix:
    sys.stdout.write(f'{args.suffix}\n')
