#!/usr/bin/env python3

import os

from .rules import BuildRules

from .kernel.config import KernelConfig
from .kernel.files import Files
from .kernel.options import Options


KERNCONF_TEMPLATE = '''
/*
 * This file acts as a template for config.c that will be generated in the
 * kernel build directory after config(8) has been successfully run.
 *
 * $FreeBSD$
 */
#include "opt_config.h"
#ifdef INCLUDE_CONFIG_FILE

/*
 * For !INCLUDE_CONFIG_FILE case, you should look at kern_mib.c. This is
 * where kernconfstring is defined then.
 */
const char kernconfstring[] __attribute__ ((section("kern_conf"))) =
"%%KERNCONFFILE%%";

#endif /* INCLUDE_CONFIG_FILE */
'''.lstrip()


class ConfigError(Exception):
    pass


def generate(configfile, machine=None, srcpath=None, buildpath='build'):
    if not os.path.exists(buildpath):
        os.mkdir(buildpath)

    if srcpath is None:
        srcpath = os.path.split(configfile)[0]  # .../conf
        srcpath = os.path.split(srcpath)[0]     # .../<machine>

        syspath, m = os.path.split(srcpath)     # .../sys

        if machine is None:
            machine = m

        srcpath = os.path.split(syspath)[0]
    else:
        syspath = os.path.join(srcpath, 'sys')
    
    if not os.path.exists(srcpath):
        raise ConfigError(f"Bad src path: {srcpath}")

    if machine is None:
        defaults = os.path.join(os.path.split(configfile)[0], 'DEFAULTS')
    else:
        defaults = os.path.join(syspath, machine, 'conf', 'DEFAULTS')

    config = KernelConfig(filenames=[defaults, configfile])

    options = [
        os.path.join(syspath, 'conf', 'options'),
        os.path.join(syspath, 'conf', f'options.{config.machine}'),
    ]

    files = [
        os.path.join(syspath, 'conf', 'files'),
        os.path.join(syspath, 'conf', f'files.{config.machine}'),
    ]

    print(f'Machine: {config.machine}')
    print(f'CPU: {config.cpu}')
    print(f'Ident: {config.ident}')
    print(f'Options: {config.options}')
    print(f'Devices: {config.devices}')

    options = Options(filenames=options)
    files = Files(filenames=files)

    options.write_headers(buildpath, config)

    # XXX we're assuming no one uses env directives anymore...
    with open(os.path.join(buildpath, 'env.c'), 'w') as env:
        env.write('#include <sys/types.h>\n')
        env.write('#include <sys/systm.h>\n')
        env.write('\n')
        env.write('int envmode = 0;\n')
        env.write('char static_env[] = {\n')
        env.write('"\\0"\n')
        env.write('};\n')

    # XXX other archs will need this to actually work...
    with open(os.path.join(buildpath, 'hints.c'), 'w') as hints:
        hints.write('#include <sys/types.h>\n')
        hints.write('#include <sys/systm.h>\n')
        hints.write('\n')
        hints.write('int hintmode = 0;\n')
        hints.write('char static_hints[] = {\n')
        hints.write('"\\0"\n')
        hints.write('};\n')

    with open(os.path.join(buildpath, 'config.c'), 'w') as conf_c:
        confdata = ['options CONFIG_AUTOGENERATED']
        confdata.append(f'ident {config.ident}')
        confdata.append(f'machine {config.machine}')
        confdata.append(f'cpu {config.cpu}')

        for makeopt in config.makeoptions:
            confdata.append(f'makeoptions {makeopt}')

        for option, value in config.options.items():
            if option == 'MAXUSERS' and value == '0':
                continue
            elif option.startswith('DEV_'):
                continue
            if value in ('1', None):
                confdata.append(f'options {option}')
            else:
                confdata.append(f'options {option}={value}')

        for device in config.devices:
            confdata.append(f'device {device}')

        confdata = '\\n\\\n'.join(confdata) + '\\n\\\n'
        conf_c.write(KERNCONF_TEMPLATE.replace('%%KERNCONFFILE%%', confdata))

    rules = BuildRules(buildpath, files, config, {
        'S': os.path.join(srcpath, 'sys'),
    })

    rules.generate_rules()


def climain():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--build', metavar='path', default='build',
                        help='Build directory name')
    parser.add_argument('-s', '--src', metavar='path', help='Path to src tree')
    parser.add_argument('-m', '--machine', metavar='name', help='Machine type name')
    parser.add_argument('configfile', nargs=1, metavar='filename',
                        help='kernel configuration file')
    args = parser.parse_args()

    generate(args.configfile[0], machine=args.machine, srcpath=args.src,
             buildpath=args.build)


if __name__ == '__main__':
    climain()
