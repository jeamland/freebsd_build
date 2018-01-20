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
