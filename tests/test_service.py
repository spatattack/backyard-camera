import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / 'device'
INSTALL_DIR = '/opt/backyard-camera/device/'


def exec_start(path):
    commands = []
    for line in (DEVICE / path).read_text().splitlines():
        if line.startswith('ExecStart='):
            value = line.split('=', 1)[1]
            commands = [] if not value else commands + [value]
    return commands


def local_imports(script):
    tree = ast.parse((DEVICE / script).read_text())
    names = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    names |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    return {name for name in names if (DEVICE / f'{name}.py').exists()}


class ServiceTests(unittest.TestCase):
    def test_service_defaults_to_motion_mode(self):
        [command] = exec_start('backyard-camera.service')
        self.assertIn(INSTALL_DIR + 'watch.py --config /etc/backyard-camera.json', command)

    def test_scheduled_only_fallback_replaces_exec_start(self):
        [command] = exec_start('scheduled-only.conf')
        self.assertIn(INSTALL_DIR + 'camera.py --config /etc/backyard-camera.json', command)

    def test_hardware_guide_installs_every_module_the_service_needs(self):
        guide = (ROOT / 'docs' / 'HARDWARE.md').read_text()
        installed = set(re.findall(re.escape(INSTALL_DIR) + r'(\w+)\.py', guide))
        needed = {'watch', 'camera'} | local_imports('watch.py') | local_imports('camera.py')
        self.assertLessEqual(needed, installed)
        self.assertIn('python3-picamera2', guide)
        self.assertIn('scheduled-only.conf', guide)


if __name__ == '__main__':
    unittest.main()
