#!/usr/bin/env python3
"""
Hercules Auto-Installer
Installs Python + dependencies + sets up Hercules
"""

import os
import sys
import subprocess
import platform
import json
from pathlib import Path


def run_cmd(cmd, shell=False):
    """Execute command"""
    try:
        result = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def detect_os():
    """Detect operating system"""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    elif system == "Linux":
        return "Linux"
    elif system == "Windows":
        return "Windows"
    return "Unknown"


def install_python_macos():
    """Install Python on macOS"""
    print("  Checking Homebrew...")
    success, _ = run_cmd("brew --version", shell=True)
    
    if not success:
        print("  Installing Homebrew...")
        cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        success, output = run_cmd(cmd, shell=True)
        if not success:
            print(f"  ✗ Homebrew install failed: {output}")
            return False
    
    print("  Installing Python 3...")
    success, output = run_cmd("brew install python3", shell=True)
    return success


def install_python_linux():
    """Install Python on Linux"""
    # Check distro
    if Path("/etc/debian_version").exists():
        print("  Installing Python 3 (Debian/Ubuntu)...")
        return run_cmd("sudo apt-get update && sudo apt-get install -y python3 python3-pip", shell=True)[0]
    
    elif Path("/etc/redhat-release").exists():
        print("  Installing Python 3 (RedHat/CentOS)...")
        return run_cmd("sudo yum install -y python3 python3-pip", shell=True)[0]
    
    elif Path("/etc/arch-release").exists():
        print("  Installing Python 3 (Arch)...")
        return run_cmd("sudo pacman -S python", shell=True)[0]
    
    return False


def install_python_windows():
    """Install Python on Windows"""
    print("  Attempting Windows Package Manager...")
    success, _ = run_cmd("winget --version", shell=True)
    
    if success:
        print("  Installing Python via winget...")
        return run_cmd("winget install -e --id Python.Python.3.11", shell=True)[0]
    
    print("  ✗ Please download Python from https://python.org")
    return False


def setup_hercules():
    """Setup Hercules directories and config"""
    print("\n✓ Setting up Hercules...")
    
    hercules_home = Path.home() / ".hercules"
    hercules_home.mkdir(exist_ok=True)
    
    # Create subdirs
    for subdir in ["cache", "plugins", "conversations"]:
        (hercules_home / subdir).mkdir(exist_ok=True)
    
    # Create models dir
    models_dir = Path.home() / "Models"
    models_dir.mkdir(exist_ok=True)
    
    # Create config if not exists
    config_file = hercules_home / "config.json"
    if not config_file.exists():
        config = {
            "model_dir": str(models_dir),
            "auto_save": True,
            "auto_save_interval": 10,
            "theme": "dark",
            "verbose": False,
            "context_window_size": 10,
            "cache_responses": False,
            "default_temp": 0.7,
            "default_tokens": 256
        }
        config_file.write_text(json.dumps(config, indent=2))
        print(f"  Created config: {config_file}")
    
    print(f"  Created dirs: {hercules_home}")
    print(f"  Models dir: {models_dir}")


def install_dependencies():
    """Install Python dependencies"""
    print("\n✓ Installing dependencies...")
    
    deps = ["gpt4all>=2.7.0", "colorama>=0.4.6", "psutil>=5.9.0"]
    
    for dep in deps:
        print(f"  Installing {dep}...")
        success, output = run_cmd(f"python3 -m pip install {dep}", shell=True)
        if not success:
            print(f"  ✗ Failed: {output}")
            return False
    
    print("  ✓ All dependencies installed")
    return True


def main():
    """Main installer"""
    print("\n" + "="*45)
    print("  Hercules v8.2.0 Auto-Installer")
    print("="*45 + "\n")
    
    # Detect OS
    os_type = detect_os()
    print(f"Detected OS: {os_type}\n")
    
    # Check/Install Python
    print("✓ Checking Python 3...")
    success, output = run_cmd("python3 --version", shell=True)
    
    if not success:
        print("  Python 3 not found. Installing...\n")
        
        if os_type == "macOS":
            success = install_python_macos()
        elif os_type == "Linux":
            success = install_python_linux()
        elif os_type == "Windows":
            success = install_python_windows()
        
        if not success:
            print("\n✗ Python installation failed")
            print("Please install manually from https://python.org")
            return False
    else:
        print(f"  {output.strip()}")
    
    # Install dependencies
    if not install_dependencies():
        return False
    
    # Setup Hercules
    setup_hercules()
    
    # Success
    print("\n" + "="*45)
    print("  Installation Complete!")
    print("="*45 + "\n")
    print("Next steps:")
    print("  1. Download GGUF model to ~/Models")
    print("     From: https://huggingface.co/TheBloke")
    print("\n  2. Run Hercules:")
    print("     python3 hercules.py")
    print("\n  3. In Hercules:")
    print("     /setup       (select model)")
    print("     /help        (show commands)")
    print("     /hagent      (view agent system)")
    print("\n")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
