"""Atlas local chat package."""

from .config import AppConfig, load_config
from .version import atlas_version

__version__ = atlas_version()

__all__ = ["AppConfig", "__version__", "atlas_version", "load_config"]
