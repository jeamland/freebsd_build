#!/usr/bin/env python3

import collections
import fnmatch
import os.path
import re


CFLAGS = '-O2 -pipe -fno-strict-aliasing -g -nostdinc --target=x86_64-unknown-freebsd -I. -I$S -I$S/contrib/libfdt -D_KERNEL -DHAVE_KERNEL_OPTION_HEADERS -include opt_global.h -fPIC -fno-common -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer -MD -MF.depend.$out -MT$out -mcmodel=kernel -mno-red-zone -mno-mmx -mno-sse -msoft-float -fno-asynchronous-unwind-tables -ffreestanding -fwrapv -fstack-protector -gdwarf-2 -Wall -Wredundant-decls -Wnested-externs -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith -Winline -Wcast-qual -Wundef -Wno-pointer-sign -D__printf__=__freebsd_kprintf__ -Wmissing-include-dirs -fdiagnostics-show-option -Wno-unknown-pragmas -Wno-error-tautological-compare -Wno-error-empty-body -Wno-error-parentheses-equality -Wno-error-unused-function -Wno-error-pointer-sign -Wno-error-shift-negative-value -Wno-error-address-of-packed-member -mno-aes -mno-avx -std=iso9899:1999'.split()
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


class KernelConfig:
    def __init__(self, filenames):
        self.machine = None
        self.ident = None
        self.cpu = []
        self.options = {'MAXUSERS': '0'}
        self.devices = set()
        self.makeoptions = []

        for filename in filenames:
            with open(filename) as fp:
                self.parse_data(fp.read())
    
    def option_set(self, option):
        if option.upper() in self.options:
            return True
        if option.lower() in self.devices:
            return True
        return False

    def parse_data(self, data):
        for line in data.splitlines():
            if line.startswith('#'):
                continue
            comment = line.find('#')
            if comment != -1:
                line = line[:comment]
            line = line.strip()
            if not line:
                continue

            directive, value = line.split()

            directive_method_name = f'directive_{directive}'
            if not hasattr(self, directive_method_name):
                raise ConfigError(f"unknown directive in kernel configuration: {directive}")

            getattr(self, directive_method_name)(value)

    def directive_machine(self, value):
        if self.machine:
            raise ConfigError("Only one machine directive may be provided")
        self.machine = value

    def directive_cpu(self, value):
        self.cpu = value

    def directive_ident(self, value):
        self.ident = value
    
    def directive_makeoptions(self, value):
        self.makeoptions.append(value)

    def directive_options(self, value):
        if '=' in value:
            option, value = value.split('=', 1)
            self.options[option] = value
        else:
            self.options[value] = None
    
    def directive_device(self, value):
        self.options[f'DEV_{value.upper()}'] = '1'
        self.devices.add(value)


class Options(dict):
    def __init__(self, filenames):
        self['MAXUSERS'] = 'opt_maxusers.h'

        for filename in filenames:
            with open(filename) as fp:
                self.parse_data(fp.read())

    def parse_data(self, data):
        for line in data.splitlines():
            if line.startswith('#'):
                continue
            comment = line.find('#')
            if comment != -1:
                line = line[:comment]
            line = line.strip()
            if not line:
                continue

            try:
                option, header = line.split()
            except ValueError:
                option = line.strip()
                header = f'opt_{option.lower()}.h'

            self[option] = header

    def write_headers(self, config):
        optfiles = {filename: [] for filename in self.values()}

        for option, value in config.options.items():
            if option not in self and option.startswith('DEV_'):
                filename = f'opt_{option[4:].lower()}.h'
                optfiles[filename] = [(option, value)]
            else:
                filename = self[option]
                optfiles[filename].append((option, value))
        
        for filename, options in optfiles.items():
            with open(filename, 'w') as optfile:
                for option, value in options:
                    optfile.write(f'#define {option}')
                    if value:
                        optfile.write(f' {value}')
                    optfile.write('\n')


class File:
    DIRECTIVES = set([
        'standard',
        'optional',
        'profiling-routine',
        'no-obj',
        'no-implicit-rule',
        'compile-with',
        'dependency',
        'before-depend',
        'clean',
        'warning',
        'obj-prefix',
        'local',
    ])

    def __init__(self, data):
        self.filename = None
        self.optional = []
        self.dependencies = []
        self.compile_with = None
        self.clean = set()
        self.obj = True
        self.implicit_rule = True
        self.obj_prefix = None
        self.profiling = False
        self.local = False
        self.before_depend = False

        self.parse_data(data)

        # XXX BEFORE DEPEND QUIRK
        if self.filename.endswith('ia32_genassym.o'):
            self.before_depend = True

    def collect_non_directives(self, data):
        elements = []
        while data and data[0] not in self.DIRECTIVES:
            elements.append(data.pop(0))
        return elements

    def quoted_string(self, data):
        string = self.collect_non_directives(data)
        string = ' '.join(string)
        if string.startswith('"') or string.startswith("'"):
            string = string[1:-1]
        return string
    
    def quoted_list(self, data):
        return [e.strip('"') for e in self.collect_non_directives(data)]

    def parse_data(self, data):
        self.filename, data = data.split(None, 1)
        data = data.split()

        while data:
            directive = data.pop(0)

            if directive not in self.DIRECTIVES:
                raise ConfigError(f'Unknown directive for {self.filename}: {directive}')
            
            if directive == 'standard':
                pass
            elif directive == 'optional':
                spec = self.collect_non_directives(data)
                self.parse_optional_spec(spec)
            elif directive == 'compile-with':
                self.compile_with = self.quoted_string(data)
            elif directive == 'clean':
                clean_files = self.quoted_list(data)
                self.clean.update([f for f in clean_files if f != self.filename])
            elif directive == 'no-obj':
                self.obj = False
            elif directive == 'no-implicit-rule':
                self.implicit_rule = False
            elif directive == 'dependency':
                self.dependencies.extend(self.quoted_list(data))
            elif directive == 'obj-prefix':
                self.obj_prefix = self.quoted_string(data)
            elif directive == 'local':
                self.local = True
            elif directive == 'profiling-routine':
                self.profiling = True
            elif directive == 'before-depend':
                self.before_depend = True
            elif directive == 'warning':
                self.warning = self.quoted_string(data)
            else:
                print(f'Skipping {directive} on {self.filename}')
                while data and data[0] not in self.DIRECTIVES:
                    data.pop(0)

    def parse_optional_spec(self, spec):
        runs = []
        run = []

        for entry in spec:
            if entry != '|':
                run.append(entry)
            else:
                runs.append(run)
                run = []
        
        if run:
            runs.append(run)
        
        self.optional = runs

    def configured(self, config):
        if not self.optional:
            return True

        for condition in self.optional:
            configured = True
            for item in condition:
                expected = True
                if item[0] == '!':
                    expected = False
                    item = item[1:]

                if config.option_set(item) is not expected:
                    configured = False
                    break
            
            if configured:
                return True
        
        return False


class Files(list):
    def __init__(self, filenames):
        for filename in filenames:
            with open(filename) as fp:
                self.parse_data(fp.read())

        self.parse_data('config.c standard local')
        self.parse_data('env.c standard local')
        self.parse_data('hints.c standard local')
        self.parse_data('vers.c standard local')
        self.parse_data('vnode_if.c standard local')

    def parse_data(self, data):
        prev_line = ''

        for line in data.splitlines():
            if line.startswith('#'):
                continue
            comment = line.find(' #')
            if comment == -1:
                comment = line.find('\t#')
            if comment != -1:
                line = line[:comment]
            line = line.rstrip()
            if not line:
                continue
            
            if line.endswith('\\'):
                prev_line += line[:-1]
                continue

            line = prev_line + line
            prev_line = ''

            self.append(File(line))


class BuildRules:
    DEFAULT_RULE_DEFINITIONS = {
        'as': {
            'command': 'cc -c $ASM_CFLAGS $in',
        },
        'awk': {
            'command': 'awk -f $in $args'
        },
        'awk_stdout': {
            'command': 'awk -f $in $args > $out'
        },
        'cc': {
            'command': '$CC -c $CFLAGS $in',
            'deps': 'gcc',
            'depfile': '.depend.$out'
        },
        'hack': {
            'command': 'touch hack.c && $CC -shared -nostdlib --target=x86_64-unknown-freebsd -fuse-ld=/Users/benno/src/llvm-build/bin/ld.lld hack.c -o $out && rm -f hack.c',
        },
        'ilink': {
            'command': 'ln -fhs $in $out',
        },
        'ld': {
            'command': '$LD -Bdynamic -T $S/conf/ldscript.$MACHINE --no-warn-mismatch --warn-common --export-dynamic --dynamic-linker /red/herring -o $out -X $in',
        },
        'sh_stdout': {
            'command': "$env sh $in > $out",
        },
        'extract_debug': {
            'command': '$OBJCOPY --only-keep-debug $in $out',
        },
        'strip_debug': {
            'command': '$OBJCOPY --strip-debug --add-gnu-debuglink=kernel.debug $in $out'
        }
    }

    DEFAULT_VARS = {
        'S': '../../..',
        'CFLAGS': '-O2 -pipe -fno-strict-aliasing -g -nostdinc --target=x86_64-unknown-freebsd -I. -I$S -I$S/contrib/libfdt -D_KERNEL -DHAVE_KERNEL_OPTION_HEADERS -include opt_global.h -fPIC -fno-common -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer -MD -MF.depend.$out -MT$out -mcmodel=kernel -mno-red-zone -mno-mmx -mno-sse -msoft-float -fno-asynchronous-unwind-tables -ffreestanding -fwrapv -fstack-protector -gdwarf-2 -Wall -Wredundant-decls -Wnested-externs -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith -Winline -Wcast-qual -Wundef -Wno-pointer-sign -D__printf__=__freebsd_kprintf__ -Wmissing-include-dirs -fdiagnostics-show-option -Wno-unknown-pragmas -Wno-error-tautological-compare -Wno-error-empty-body -Wno-error-parentheses-equality -Wno-error-unused-function -Wno-error-pointer-sign -Wno-error-shift-negative-value -Wno-error-address-of-packed-member -mno-aes -mno-avx -std=iso9899:1999',
        'CFLAGS_GENASSYM': '-O2 -pipe -fno-strict-aliasing -g -nostdinc --target=x86_64-unknown-freebsd -I. -I$S -I$S/contrib/libfdt -D_KERNEL -DHAVE_KERNEL_OPTION_HEADERS -include opt_global.h -fPIC -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer -MD -MF.depend.$out -MT$out -mcmodel=kernel -mno-red-zone -mno-mmx -mno-sse -msoft-float -fno-asynchronous-unwind-tables -ffreestanding -fwrapv -fstack-protector -gdwarf-2 -Wall -Wredundant-decls -Wnested-externs -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith -Winline -Wcast-qual -Wundef -Wno-pointer-sign -D__printf__=__freebsd_kprintf__ -Wmissing-include-dirs -fdiagnostics-show-option -Wno-unknown-pragmas -Wno-error-tautological-compare -Wno-error-empty-body -Wno-error-parentheses-equality -Wno-error-unused-function -Wno-error-pointer-sign -Wno-error-shift-negative-value -Wno-error-address-of-packed-member -mno-aes -mno-avx -std=iso9899:1999',
        'ASM_CFLAGS': '-x assembler-with-cpp -DLOCORE $CFLAGS',
        'OBJCOPY': 'gobjcopy',
        'NM': 'nm',
        'CC': 'cc',
        'LD': '/Users/benno/src/llvm-build/bin/ld.lld',
    }

    DEFAULT_BUILDS = [
        ('machine', [], 'ilink', ['$S/$MACHINE/include'], [], [], {}),
        ('x86', [], 'ilink', ['$S/x86/include'], [], [], {}),
        ('vnode_if.h', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-h'}),
        ('vnode_if_newproto.h', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-p'}),
        ('vnode_if_typedef.h', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-q'}),
        ('vnode_if.c', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-c'}),
        ('genassym.o', [], 'cc', ['$S/$MACHINE/$MACHINE/genassym.c'], [], [], {'CFLAGS': '$CFLAGS_GENASSYM'}),
        ('assym.s', [], 'sh_stdout', ['$S/kern/genassym.sh', 'genassym.o'], [], [], {'env': "NM='nm' NMFLAGS=''"}),
        ('hack.pico', [], 'hack', [], [], [], {}),
    ]

    DEFAULT_IMPLICIT_DEPS = [
        'vnode_if.h'
    ]

    def __init__(self, files, config):
        self.files = files
        self.config = config

        self.patterns = []
    
    def add_pattern(self, pattern, processor):
        self.patterns.append((re.compile(pattern), processor))
    
    def generate_rules(self, filename='build.ninja'):
        rules = {}
        rule_counter = 0
        early_builds = list(self.DEFAULT_BUILDS)
        builds = []
        before_depends = []
        objs = []

        for f in files:
            if not f.configured(self.config):
                continue
            if f.profiling:
                continue
            if not f.compile_with:
                extension = f.filename.rsplit('.', 1)[1]

                if extension == 'c':
                    obj = os.path.split(f.filename)[1]
                    obj = obj[:-1] + 'o'
                    src = f.filename
                    if not f.local:
                        src = f'$S/{src}'
                    builds.append((obj, [], 'cc', [src], [], [], {}))
                    if f.obj:
                        objs.append(obj)
                elif extension == 'm':
                    obj = os.path.split(f.filename)[1]
                    c_obj = obj[:-1] + 'c'
                    h_obj = obj[:-1] + 'h'
                    obj = obj[:-1] + 'o'

                    builds.extend([
                        (c_obj, [], 'awk', ['$S/tools/makeobjops.awk', f'$S/{f.filename}'], [], [], {'args': '-c'}),
                        (obj, [], 'cc', [c_obj], [], [], {}),
                    ])

                    before_depends.append(h_obj)
                    early_builds.append(
                        (h_obj, [], 'awk', ['$S/tools/makeobjops.awk', f'$S/{f.filename}'], [], [], {'args': '-h'})
                    )
                    if f.obj:
                        objs.append(obj)
                elif extension == 'S':
                    obj = os.path.split(f.filename)[1]
                    obj = obj[:-1] + 'o'
                    builds.append((obj, [], 'as', [f'$S/{f.filename}'], [], [], {}))
                    if f.obj:
                        objs.append(obj)
                else:
                    raise ConfigError(f'No idea what to do with {f.filename}')
            else:
                for regex, processor in self.patterns:
                    match = regex.match(f.compile_with)
                    if not match:
                        continue

                    build = processor(f, match)
                    if f.before_depend:
                        before_depends.append(build[0])
                        early_builds.append(build)
                    else:
                        builds.append(build)

                    if f.obj:
                        objs.append(build[0])

                    break
                else:
                    rule = f.compile_with
                    rule = rule.replace('${.IMPSRC}', '$in')
                    rule = rule.replace('${.TARGET}', '$out')
                    rule = re.sub(r'\$\{(.*?)\}', '$\\1', rule)

                    if rule in rules:
                        rule_name = rules[rule]
                    else:
                        rule_name = rules[rule] = f'rule{rule_counter}'
                        rule_counter += 1

                    build = (f.filename, [], rule_name, f.dependencies, [], [], {})
                    if f.before_depend:
                        before_depends.append(build[0])
                        early_builds.append(build)
                    else:
                        builds.append(build)

                    if f.obj:
                        objs.append(build[0])

        objs.append('hack.pico')
        objs.append('locore.o')

        with open(filename, 'w') as build:
            build.write(f'MACHINE = {config.machine}\n')
            for name, value in self.DEFAULT_VARS.items():
                build.write(f'{name} = {value}\n')

            build.write('\n')

            for name, variables in self.DEFAULT_RULE_DEFINITIONS.items():
                build.write(f'rule {name}\n')
                for varname, value in variables.items():
                    build.write(f'  {varname} = {value}\n')
            build.write('rule newvers\n')
            build.write(f'  command = MAKE=./versmake.sh sh $S/conf/newvers.sh {config.ident}\n')
            for command, name in rules.items():
                build.write(f'rule {name}\n  command = {command}\n')
            build.write('\n')

            for obj, implicit_outs, rule, deps, implicit_deps, order_deps, variables in early_builds:
                build.write(f'build {obj}')
                if implicit_outs:
                    build.write(f' | {" ".join(implicit_outs)}')
                build.write(f': {rule} {" ".join(deps)}')
                if implicit_deps:
                    build.write(f' | {" ".join(implicit_deps)}')
                if order_deps:
                    build.write(f' || {" ".join(order_deps)}')
                build.write('\n')
                for varname, value in variables.items():
                    build.write(f'  {varname} = {value}\n')

            for obj, implicit_outs, rule, deps, implicit_deps, order_deps, variables in builds:
                build.write(f'build {obj}')
                if implicit_outs:
                    build.write(f' | {" ".join(implicit_outs)}')
                build.write(f': {rule} {" ".join(deps)}')
                build.write(f' | {" ".join(before_depends + implicit_deps)}')
                if order_deps:
                    build.write(f' || {" ".join(order_deps)}')
                build.write('\n')
                for varname, value in variables.items():
                    build.write(f'  {varname} = {value}\n')
            
            build.write('build vers.c: newvers\n')

            build.write(f'build kernel.full: ld {" ".join(objs)}\n')
            build.write(f'build kernel.debug: extract_debug kernel.full\n')
            build.write(f'build kernel: strip_debug kernel.full | kernel.debug\n')

def as_rule(f, match):
    return (f.filename, [], 'as', [f.dependencies[0]], f.dependencies[1:], [], {})


def awk_rule(f, match):
    return (f.filename, [], 'awk', match.groups(), [], [], {})


def awk_stdout_rule(f, match):
    groups = match.groups()
    return (groups[-1], [], 'awk_stdout', groups[:-1], [], [], {})


def cc_rule(f, match):
    if 'NORMAL_C' in match.string:
        args = re.match(r'.*NORMAL_C:(.*?)\}', match.string)
        obj = os.path.split(f.filename)[1]
        obj = obj[:-1] + 'o'
        deps = [f'$S/{f.filename}']
        imp_deps = []
    else:
        args = re.match(r'.*CFLAGS:(.*?)\}', match.string)
        obj = f.filename
        deps = [f.dependencies[0]]
        imp_deps = f.dependencies[1:]

    cflags = list(CFLAGS)
    for arg in args.group(1).split(':'):
        if arg[0] == 'N':
            arg = arg[1:]
            if '*' in arg:
                cflags = [f for f in cflags if not fnmatch.fnmatchcase(f, arg)]
            else:
                cflags = [f for f in cflags if f != arg]

    return (obj, [], 'cc', deps, imp_deps, [], {'CFLAGS': ' '.join(cflags)})


def genassym_rule(f, match):
    genassym, src = match.groups()

    return (f.filename, [], 'sh_stdout', match.groups(), [], [], {'env': "NM='nm' NMFLAGS=''"})


if __name__ == '__main__':
    import os
    import sys

    configfile = sys.argv[1]
    defaults = os.path.join(os.path.split(configfile)[0], 'DEFAULTS')

    sysdir = os.path.split(os.path.abspath(configfile))[0]
    sysdir = os.path.split(sysdir)[0]
    sysdir = os.path.split(sysdir)[0]

    config = KernelConfig(filenames=[defaults, configfile])

    options = [
        os.path.join(sysdir, 'conf', 'options'),
        os.path.join(sysdir, 'conf', f'options.{config.machine}'),
    ]

    files = [
        os.path.join(sysdir, 'conf', 'files'),
        os.path.join(sysdir, 'conf', f'files.{config.machine}'),
    ]

    print(f'Machine: {config.machine}')
    print(f'CPU: {config.cpu}')
    print(f'Ident: {config.ident}')
    print(f'Options: {config.options}')
    print(f'Devices: {config.devices}')

    options = Options(filenames=options)
    files = Files(filenames=files)

    options.write_headers(config)

    # XXX we're assuming no one uses env directives anymore...
    with open('env.c', 'w') as env:
        env.write('#include <sys/types.h>\n')
        env.write('#include <sys/systm.h>\n')
        env.write('\n')
        env.write('int envmode = 0;\n')
        env.write('char static_env[] = {\n')
        env.write('"\\0"\n')
        env.write('};\n')

    # XXX other archs will need this to actually work...
    with open('hints.c', 'w') as hints:
        hints.write('#include <sys/types.h>\n')
        hints.write('#include <sys/systm.h>\n')
        hints.write('\n')
        hints.write('int hintmode = 0;\n')
        hints.write('char static_hints[] = {\n')
        hints.write('"\\0"\n')
        hints.write('};\n')

    with open('config.c', 'w') as conf_c:
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

    rules = BuildRules(files, config)

    rules.add_pattern(r'\$\{AWK\} -f (\S+) (\S+) > (\S+)', awk_stdout_rule)
    rules.add_pattern(r'\$\{AWK\} -f (\S+) (\S+)', awk_rule)
    rules.add_pattern(r'\$\{NORMAL_S\}', as_rule)
    rules.add_pattern(r'^\$\{NORMAL_C', cc_rule)
    rules.add_pattern(r'^\$\{CC\}', cc_rule)
    rules.add_pattern(r'.*(\$S/kern/genassym.sh) (\S+)', genassym_rule)

    rules.generate_rules()