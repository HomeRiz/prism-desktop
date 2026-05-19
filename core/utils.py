import sys
import os
import platform
from pathlib import Path

_LINUX_CA_BUNDLES = [
    "/etc/ssl/certs/ca-certificates.crt",  # Debian / Ubuntu / Arch
    "/etc/pki/tls/certs/ca-bundle.crt",    # RHEL / CentOS / Fedora
    "/etc/ssl/ca-bundle.pem",              # openSUSE
    "/etc/pki/tls/cert.pem",              # Amazon Linux
]

def configure_ssl() -> None:
    """Prefer the system CA bundle on Linux to avoid stale bundled certifi certs."""
    if platform.system() != "Linux":
        return
    # Find the first available system CA bundle
    system_bundle = os.environ.get("SSL_CERT_FILE")
    if not system_bundle:
        for path in _LINUX_CA_BUNDLES:
            if Path(path).exists():
                system_bundle = path
                break
    if not system_bundle:
        return
    # ssl module (used by aiohttp/websockets)
    os.environ.setdefault("SSL_CERT_FILE", system_bundle)
    # requests / urllib3
    os.environ.setdefault("REQUESTS_CA_BUNDLE", system_bundle)


# Cross-platform system font
def get_system_font() -> str:
    """Get the appropriate system UI font for the current platform."""
    system = platform.system()
    if system == 'Windows':
        return 'Segoe UI'
    elif system == 'Darwin':
        return 'SF Pro Display'
    else:  # Linux
        return 'Ubuntu'

SYSTEM_FONT = get_system_font()

def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to a resource, works for dev and for PyInstaller.
    
    Args:
        relative_path: Relative path to the resource (e.g., 'icon.png')
        
    Returns:
        Path object pointing to the absolute path of the resource.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
        return Path(base_path) / relative_path
    except Exception:
        # Dev mode: use current directory
        # Dev mode: use project root (parent of core)
        return Path(__file__).parent.parent / relative_path


def get_platform_config_dir() -> Path:
    """
    Get the appropriate config directory for each platform.
    
    Returns:
        Path to the platform-specific config directory.
    """
    system = platform.system()
    
    if system == 'Windows':
        # Windows: %APPDATA%/PrismDesktop
        return Path(os.getenv('APPDATA', Path.home())) / "PrismDesktop"
    elif system == 'Darwin':
        # macOS: ~/Library/Application Support/PrismDesktop
        return Path.home() / "Library" / "Application Support" / "PrismDesktop"
    else:
        # Linux: ~/.config/PrismDesktop (XDG compliant)
        xdg_config = os.getenv('XDG_CONFIG_HOME', str(Path.home() / '.config'))
        return Path(xdg_config) / "PrismDesktop"


def get_config_path(filename: str = "config.json") -> Path:
    """
    Get absolute path to the configuration file.
    
    Priority:
    1. Dev Mode: Use source directory.
    2. Portable Mode: Use directory next to executable (if config.json exists there).
    3. Installed Mode: Use platform-specific config directory.
    
    Args:
        filename: Name of the config file.
        
    Returns:
        Path object pointing to the absolute path of the config file.
    """
    if getattr(sys, 'frozen', False):
        # We are running as a bundled executable
        exe_path = Path(sys.executable).parent
        portable_config = exe_path / filename
        
        # Portable Mode: If config exists next to exe, use it.
        if portable_config.exists():
            return portable_config
            
        # Installed Mode: Use platform-specific directory
        app_data = get_platform_config_dir()
        app_data.mkdir(parents=True, exist_ok=True)
        return app_data / filename
    else:
        # Dev mode: config sits with source code
        # Dev mode: config sits in project root
        return Path(__file__).parent.parent / filename
