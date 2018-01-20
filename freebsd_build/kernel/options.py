import os.path


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

    def write_headers(self, path, config):
        optfiles = {filename: [] for filename in self.values()}

        for option, value in config.options.items():
            if option not in self and option.startswith('DEV_'):
                filename = f'opt_{option[4:].lower()}.h'
                optfiles[filename] = [(option, value)]
            else:
                filename = self[option]
                optfiles[filename].append((option, value))
        
        for filename, options in optfiles.items():
            with open(os.path.join(path, filename), 'w') as optfile:
                for option, value in options:
                    optfile.write(f'#define {option}')
                    if value:
                        optfile.write(f' {value}')
                    optfile.write('\n')
