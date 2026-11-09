"""Where things live: the skill folder (read-only), the user's folder, and the workspace inside a project."""
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]          # plugin/skills/floored
APP_DIR = SKILL_DIR / 'app'
WEB_DIR = APP_DIR / 'web'
SAMPLE_DIR = APP_DIR / 'sample'
PLUGIN_JSON = SKILL_DIR.parents[1] / '.claude-plugin' / 'plugin.json'     # plugin/.claude-plugin/plugin.json


def user_dir() -> Path:
    """The per-user folder (config.json, downloaded tools). FLOORED_HOME moves it."""
    env = os.environ.get('FLOORED_HOME')
    return Path(env).expanduser() if env else Path.home() / '.floored'


def rvm_model_path() -> Path:
    """The RVM weights. FLOORED_RVM_MODEL points somewhere else."""
    env = os.environ.get('FLOORED_RVM_MODEL')
    return Path(env).expanduser() if env else Path.home() / '.cache' / 'rvm' / 'rvm_mobilenetv3_fp32.onnx'


class Workspace:
    """A project's `floored/` folder: takes, exports, settings, and the running server's files."""

    def __init__(self, project):
        self.project = Path(project)
        self.root = self.project / 'floored'
        self.takes = self.root / 'takes'
        self.exports = self.root / 'exports'
        self.settings = self.root / 'settings.json'
        self.settings_dir = self.root / 'settings'            # per-take studio settings: <id>.json (the sample's too)
        self.server_file = self.root / '.server.json'
        self.log_file = self.root / 'server.log'

    def ensure(self):
        self.takes.mkdir(parents=True, exist_ok=True)
        self.exports.mkdir(parents=True, exist_ok=True)
        return self
