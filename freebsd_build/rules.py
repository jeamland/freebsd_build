import fnmatch
import os
import re


CFLAGS = '-O2 -pipe -fno-strict-aliasing -g -nostdinc --target=x86_64-unknown-freebsd -I. -I$S -I$S/contrib/libfdt -D_KERNEL -DHAVE_KERNEL_OPTION_HEADERS -include opt_global.h -fPIC -fno-common -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer -MD -MF.depend.$out -MT$out -mcmodel=kernel -mno-red-zone -mno-mmx -mno-sse -msoft-float -fno-asynchronous-unwind-tables -ffreestanding -fwrapv -fstack-protector -gdwarf-2 -Wall -Wredundant-decls -Wnested-externs -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith -Winline -Wcast-qual -Wundef -Wno-pointer-sign -D__printf__=__freebsd_kprintf__ -Wmissing-include-dirs -fdiagnostics-show-option -Wno-unknown-pragmas -Wno-error-tautological-compare -Wno-error-empty-body -Wno-error-parentheses-equality -Wno-error-unused-function -Wno-error-pointer-sign -Wno-error-shift-negative-value -Wno-error-address-of-packed-member -mno-aes -mno-avx -std=iso9899:1999'.split()


class Build:
    def __init__(self, output, implicit_outputs, rule, inputs, implicit_dependencies, order_dependencies, variables=None):
        self.output = output
        self.implicit_outputs = implicit_outputs
        self.rule = rule
        self.inputs = inputs
        self.implicit_dependencies = implicit_dependencies
        self.order_dependencies = order_dependencies
        self.variables = variables or {}

    def __str__(self):
        build = f'build {self.output}'
        if self.implicit_outputs:
            build += f' | {" ".join(self.implicit_outputs)}'
        build += f': {self.rule} {" ".join(self.inputs)}'
        if self.implicit_dependencies:
            build += f' | {" ".join(self.implicit_dependencies)}'
        if self.order_dependencies:
            build += f' || {" ".join(self.order_dependencies)}'
        if self.variables:
            for name, value in self.variables.items():
                build += f'\n  {name} = {value}'

        return build


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
        'freebsd-config':{
            'command': 'freebsd-config -b . $in',
            'generator': '1',
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
        'ASM_CFLAGS': '-x assembler-with-cpp -DLOCORE $CFLAGS',
        'OBJCOPY': 'gobjcopy',
        'NM': 'nm',
        'CC': 'cc',
        'LD': '/Users/benno/src/llvm-build/bin/ld.lld',
    }

    DEFAULT_BUILDS = [
        Build('machine', [], 'ilink', ['$S/$MACHINE/include'], [], [], {}),
        Build('x86', [], 'ilink', ['$S/x86/include'], [], [], {}),
        Build('vnode_if.h', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-h'}),
        Build('vnode_if_newproto.h', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-p'}),
        Build('vnode_if_typedef.h', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-q'}),
        Build('vnode_if.c', [], 'awk', ['$S/tools/vnode_if.awk', '$S/kern/vnode_if.src'], [], [], {'args': '-c'}),
        Build('genassym.o', [], 'cc', ['$S/$MACHINE/$MACHINE/genassym.c'], [], [], {'CFLAGS': '$CFLAGS_GENASSYM'}),
        Build('assym.s', [], 'sh_stdout', ['$S/kern/genassym.sh', 'genassym.o'], [], [], {'env': "NM='nm' NMFLAGS=''"}),
        Build('hack.pico', [], 'hack', [], [], [], {}),
    ]

    DEFAULT_IMPLICIT_DEPS = [
        'vnode_if.h'
    ]

    PATTERNS = []

    def __init__(self, path, files, config, vars=None):
        self.path = path
        self.files = files
        self.config = config

        self.vars = dict(self.DEFAULT_VARS)
        if vars:
            self.vars.update(vars)

    @classmethod    
    def add_pattern(cls, pattern, processor):
        cls.PATTERNS.append((re.compile(pattern), processor))
    
    @classmethod
    def add_for_pattern(cls, pattern):
        def f(processor):
            cls.add_pattern(pattern, processor)
            return processor
        return f

    def generate_rules(self, filename='build.ninja'):
        rules = {}
        rule_counter = 0
        early_builds = list(self.DEFAULT_BUILDS)
        builds = []
        before_depends = []
        objs = ['locore.o']

        filename = os.path.join(self.path, filename)

        self.vars['CFLAGS'] = ' '.join(CFLAGS)
        cflags_genassym = [f for f in CFLAGS if f not in ('-flto', '-fno-common')]
        self.vars['CFLAGS_GENASSYM'] = ' '.join(cflags_genassym)
        self.vars['KERNEL_CONFIG'] = self.config.filename

        for f in self.files:
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
                    builds.append(Build(obj, [], 'cc', [src], [], [], {}))
                    if f.obj:
                        objs.append(obj)
                elif extension == 'm':
                    obj = os.path.split(f.filename)[1]
                    c_obj = obj[:-1] + 'c'
                    h_obj = obj[:-1] + 'h'
                    obj = obj[:-1] + 'o'

                    builds.extend([
                        Build(c_obj, [], 'awk', ['$S/tools/makeobjops.awk', f'$S/{f.filename}'], [], [], {'args': '-c'}),
                        Build(obj, [], 'cc', [c_obj], [], [], {}),
                    ])

                    before_depends.append(h_obj)
                    early_builds.append(
                        Build(h_obj, [], 'awk', ['$S/tools/makeobjops.awk', f'$S/{f.filename}'], [], [], {'args': '-h'})
                    )
                    if f.obj:
                        objs.append(obj)
                elif extension == 'S':
                    obj = os.path.split(f.filename)[1]
                    obj = obj[:-1] + 'o'
                    builds.append(Build(obj, [], 'as', [f'$S/{f.filename}'], [], [], {}))
                    if f.obj:
                        objs.append(obj)
                else:
                    raise ConfigError(f'No idea what to do with {f.filename}')
            else:
                for regex, processor in self.PATTERNS:
                    match = regex.match(f.compile_with)
                    if not match:
                        continue

                    build = processor(f, match)
                    if f.before_depend:
                        before_depends.append(build.output)
                        early_builds.append(build)
                    else:
                        builds.append(build)

                    if f.obj:
                        objs.append(build.output)

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

                    build = Build(f.filename, [], rule_name, f.dependencies, [], [], {})
                    if f.before_depend:
                        before_depends.append(build.output)
                        early_builds.append(build)
                    else:
                        builds.append(build)

                    if f.obj:
                        objs.append(build.output)

        objs.append('hack.pico')

        with open(filename, 'w') as build:
            build.write(f'MACHINE = {self.config.machine}\n')

            for name in ('S', 'CFLAGS'):
                value = self.vars.pop(name)
                build.write(f'{name} = {value}\n')
            for name, value in self.vars.items():
                build.write(f'{name} = {value}\n')

            build.write('\n')

            for name, variables in self.DEFAULT_RULE_DEFINITIONS.items():
                build.write(f'rule {name}\n')
                for varname, value in variables.items():
                    build.write(f'  {varname} = {value}\n')
            build.write('rule newvers\n')
            build.write(f'  command = MAKE=./versmake.sh sh $S/conf/newvers.sh {self.config.ident}\n')
            for command, name in rules.items():
                build.write(f'rule {name}\n  command = {command}\n')
            build.write('\n')

            for b in early_builds:
                build.write(f'{b}\n')

            for b in builds:
                build.write(f'{b}\n')
            
            build.write('build vers.c | version: newvers\n')

            build.write(f'build kernel.full: ld {" ".join(objs)}\n')
            build.write(f'build kernel.debug: extract_debug kernel.full\n')
            build.write(f'build kernel: strip_debug kernel.full | kernel.debug\n')

            build.write('\n')
            build.write(f'build build.ninja: freebsd-config $KERNEL_CONFIG\n')


@BuildRules.add_for_pattern(r'\$\{AWK\} -f (\S+) (\S+) > (\S+)')
def awk_stdout_rule(f, match):
    groups = match.groups()
    return Build(groups[-1], [], 'awk_stdout', groups[:-1], [], [], {})


@BuildRules.add_for_pattern(r'\$\{AWK\} -f (\S+) (\S+)')
def awk_rule(f, match):
    return Build(f.filename, [], 'awk', match.groups(), [], [], {})


@BuildRules.add_for_pattern(r'\$\{NORMAL_S\}')
def as_rule(f, match):
    return Build(f.filename, [], 'as', [f.dependencies[0]], f.dependencies[1:], [], {})


@BuildRules.add_for_pattern(r'^\$\{NORMAL_C')
@BuildRules.add_for_pattern(r'^\$\{CC\}')
def cc_rule(f, match):
    print(match.string)
    cflags = list(CFLAGS)
    if 'NORMAL_C' in match.string:
        args = re.match(r'.*NORMAL_C:(.*?)\}', match.string)
        obj = os.path.split(f.filename)[1]
        obj = obj[:-1] + 'o'
        deps = [f'$S/{f.filename}']
        imp_deps = []
        bits = match.string.split()[1:]
        cflags.extend(bits)
    else:
        args = re.match(r'.*CFLAGS:(.*?)\}', match.string)
        obj = f.filename
        deps = [f.dependencies[0]]
        imp_deps = f.dependencies[1:]

    if args:
        for arg in args.group(1).split(':'):
            if arg[0] == 'N':
                arg = arg[1:]
                if '*' in arg:
                    cflags = [f for f in cflags if not fnmatch.fnmatchcase(f, arg)]
                else:
                    cflags = [f for f in cflags if f != arg]


    return Build(obj, [], 'cc', deps, imp_deps, [], {'CFLAGS': ' '.join(cflags)})


@BuildRules.add_for_pattern(r'.*(\$S/kern/genassym.sh) (\S+)')
def genassym_rule(f, match):
    genassym, src = match.groups()

    return Build(f.filename, [], 'sh_stdout', match.groups(), [], [], {'env': "NM='nm' NMFLAGS=''"})
