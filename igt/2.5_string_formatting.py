"""
Classic formatting
"""
import dis
from string import Template

name = "Bob"
error = 50159747054

classic_string = "Hello, %s! Error: %x"
print(classic_string % (name, error))

"""
Modern formatting
"""

modern_string = "Hello, {name}! Error: {error:x}"
print(modern_string.format(name=name, error=error))

another_modern_string = "Hello, {}! Error: {:x}"
print(another_modern_string.format(name, error))

"""
F-strings
"""


def greet(name: str, error: int):
    return f"Hello, {name}! Error: {error:x}"


print(greet(name, error))

dis.dis(greet)  # Disassemble function call

"""
String templates

Used for user input formatting
"""

template_str = Template("Hello, $name! Error: $error")
print(template_str.substitute(name=name, error=error))

SECRET = "It's a secret and it's secret"


class Error:
    def __init__(self):
        """
        Vulnerability example error
        """
        pass


err = Error()
user_input = "{error.__init__.__globals__[SECRET]}"

print(user_input.format(error=err))

try:
    print(Template("$" + user_input).substitute(error=err))
except ValueError:
    print("Invalid placeholder")
