# Hercules Installation Guide

## Quick Start (Auto-Install)

### Python Script (Recommended - All Platforms)
```bash
python3 install.py
```
Auto-installs Python + deps + setup

### Shell Script (macOS/Linux)
```bash
bash install.sh
```
Auto-detects OS, installs Python, deps, setup

### Batch Script (Windows)
```cmd
install.bat
```
Auto-installs Python via winget, deps, setup

---

## What Gets Installed

**Python**: 3.8+ (auto-installed if missing)
**Deps**: gpt4all, colorama, psutil
**Dirs**: ~/.hercules (config, cache, plugins), ~/Models (GGUF files)

---

## Installation Methods

| Method | Command | OS | Auto-Python |
|--------|---------|----|----|
| **Python Script** | `python3 install.py` | All | Yes |
| **Shell Script** | `bash install.sh` | macOS/Linux | Yes |
| **Batch Script** | `install.bat` | Windows | Yes |
| **Manual** | See below | All | No |

### Manual Installation
```bash
# 1. Install Python from python.org (if not present)
# 2. Install deps
pip install -r requirements.txt

# 3. Create dirs
mkdir -p ~/.hercules/{cache,plugins,conversations}
mkdir -p ~/Models

# 4. Run
python3 hercules.py
```

---

## Python Auto-Install Details

**macOS:**
- Installs Homebrew if missing
- Runs: `brew install python3`

**Linux:**
- Debian/Ubuntu: `sudo apt install python3`
- RedHat/CentOS: `sudo yum install python3`
- Arch: `sudo pacman -S python`

**Windows:**
- Runs: `winget install Python.Python.3.11`
- Or: Download from python.org if winget fails

---

## Model Download

1. Visit: https://huggingface.co/TheBloke
2. Search: "Mistral-7B" or "Llama-2"
3. Download: `.Q4_K_M.gguf` file
4. Move to: `~/Models/`

### Recommended
- **Mistral 7B** (4GB) - Best all-around
- **Llama 2 7B** (3.8GB) - Good for chat
- **Phi 2.7B** (1.6GB) - Fastest/lightest

---

## Troubleshooting

**Python still not found after install?**
- Manually download from python.org
- Add to PATH (Windows)
- Restart terminal/shell

**pip install fails?**
```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

**Model won't load?**
```
1. /models scan (check if found)
2. Download different quantization (.Q4_K vs .F32)
3. Check disk space available
```

**Out of memory?**
```
Use smaller model: Phi instead of Mistral
Reduce /tokens 128
Use quantized version
```

---

## System Requirements

- **CPU**: 4+ cores (8+ recommended)
- **RAM**: 4GB+ (16GB recommended)
- **Disk**: 8GB+ for Hercules + model
- **Python**: 3.8+
- **OS**: macOS 10.14+, Ubuntu 18.04+, Windows 10+

---

## Verification

```bash
# Check Python
python3 --version

# Check deps
python3 -c "import gpt4all, colorama, psutil"

# Check dirs
ls ~/.hercules/
ls ~/Models/

# Run Hercules
python3 hercules.py
```

---

## Next Steps

1. Run installer (one of 3 methods)
2. Download GGUF model to ~/Models/
3. Run: `python3 hercules.py`
4. Type: `/setup` then select model
5. Type: `/help` for commands

Enjoy! 🎉
