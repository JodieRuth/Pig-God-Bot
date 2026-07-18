import importlib.util
from pathlib import Path

COMMAND_MODULE = Path(__file__).with_name("_image_pool_commands.py")
spec = importlib.util.spec_from_file_location("local_onebot_rpp_pool_commands", COMMAND_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载图片池命令模块")
commands = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commands)

COMMANDS = commands.create_privileged_pool_commands("rpp", "/rpp")
