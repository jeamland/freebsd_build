class KernelConfig:
    def __init__(self, filenames):
        self.filename = filenames[-1]

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
