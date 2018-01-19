#!/usr/bin/env python3

import argparse
import sys

def file2c(fp_in, fp_out, maxcount=0, pretty=False, hex=False, prefix='', suffix=''):
    if prefix:
        fp_out.write(f'{prefix}\n')

    count = linepos = 0

    for byte in fp_in.read():
        if count:
            linepos += fp_out.write(',')

        if (maxcount == 0 and linepos > 70) or (maxcount > 0 and count >= maxcount):
            fp_out.write('\n')
            count = linepos = 0

        if pretty:
            if count:
                linepos += fp_out.write(' ')
            else:
                fp_out.write('\t')
                linepos += 8

        if hex:
            linepos += fp_out.write(f'0x{byte:02x}')
        else:
            linepos += fp_out.write(f'{byte:d}')
        
        count += 1

    fp_out.write('\n')
    if suffix:
        fp_out.write(f'{suffix}\n')

def climain():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--maxcount', type=int, metavar='count', help='Maximum number of bytes per line')
    parser.add_argument('-s', '--pretty', action='store_true', help='Be more style(9) compliant')
    parser.add_argument('-x', '--hex', action='store_true', help='Print hexadecimal numbers')
    parser.add_argument('prefix', nargs='?', default='')
    parser.add_argument('suffix', nargs='?', default='')
    args = parser.parse_args()

    file2c(sys.stdin.buffer, sys.stdout, args.maxcount or 0, args.pretty, args.hex, args.prefix, args.suffix)
