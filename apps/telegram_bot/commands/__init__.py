from .basic import register_basic_commands
from .models import register_models_commands
from .execution import register_execution_commands
from .reporting import register_reporting_commands

def register_all(registry):
    register_basic_commands(registry)
    register_models_commands(registry)
    register_execution_commands(registry)
    register_reporting_commands(registry)
