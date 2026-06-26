#!/bin/bash
# Hercules v8.2.0 Installer - macOS/Linux/Windows (WSL)

set -e

echo "╔════════════════════════════════════════╗"
echo "║  Hercules v8.2.0 Installer             ║"
echo "║  Hierarchical AI Agent System           ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Detect OS
OS_TYPE=$(uname -s)
case "$OS_TYPE" in
    Darwin)
        OS_NAME="macOS"
        ;;
    Linux)
        OS_NAME="Linux"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        OS_NAME="Windows (WSL)"
        ;;
    *)
        OS_NAME="Unknown"
        ;;
esac

echo "Detected OS: $OS_NAME"
echo ""

# Check/Install Python
echo "✓ Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "  Python 3 not found. Installing..."
    
    if [ "$OS_NAME" = "macOS" ]; then
        # macOS - try brew first
        if ! command -v brew &> /dev/null; then
            echo "  Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        echo "  Installing Python 3 via Homebrew..."
        brew install python3
    elif [ "$OS_NAME" = "Linux" ]; then
        # Linux - detect distro
        if [ -f /etc/debian_version ]; then
            echo "  Installing Python 3 via apt..."
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip
        elif [ -f /etc/redhat-release ]; then
            echo "  Installing Python 3 via yum..."
            sudo yum install -y python3 python3-pip
        elif [ -f /etc/arch-release ]; then
            echo "  Installing Python 3 via pacman..."
            sudo pacman -S python
        else
            echo "  ✗ Unknown Linux distro. Install Python 3 manually."
            exit 1
        fi
    else
        echo "  ✗ Please install Python 3.8+ from python.org"
        exit 1
    fi
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "  ✓ Found Python $PYTHON_VERSION"
echo ""

# Create directory structure
echo "✓ Creating directories..."
HERCULES_HOME="$HOME/.hercules"
mkdir -p "$HERCULES_HOME"/{cache,plugins,conversations}
echo "  Created $HERCULES_HOME"
echo ""

# Install dependencies
echo "✓ Installing dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install gpt4all colorama psutil
echo "  Dependencies installed"
echo ""

# Create models directory
echo "✓ Setting up models directory..."
MODELS_DIR="$HOME/Models"
mkdir -p "$MODELS_DIR"
echo "  Created $MODELS_DIR"
echo "  Download GGUF models to: $MODELS_DIR"
echo ""

# Download sample model (optional)
read -p "Download sample model (Mistral 7B, ~4GB)? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "✓ Downloading Mistral 7B..."
    cd "$MODELS_DIR"
    if ! command -v wget &> /dev/null; then
        python3 -m pip install wget
    fi
    # Download from HuggingFace via gpt4all
    python3 << 'PYTHON_SCRIPT'
from gpt4all import GPT4All
try:
    model = GPT4All("Mistral")
    print("✓ Model downloaded successfully")
except Exception as e:
    print(f"Could not auto-download: {e}")
    print("Download manually from: https://huggingface.co/TheBloke")
PYTHON_SCRIPT
fi
echo ""

# Create launcher script
echo "✓ Creating launcher..."
LAUNCHER="$HOME/.local/bin/hercules"
mkdir -p "$(dirname "$LAUNCHER")"
cat > "$LAUNCHER" << 'LAUNCHER_SCRIPT'
#!/bin/bash
cd "$(dirname "$0")" || exit
python3 hercules.py "$@"
LAUNCHER_SCRIPT
chmod +x "$LAUNCHER"

# Copy hercules.py
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "hercules.py" ]; then
    cp hercules.py "$HOME/.local/bin/"
    echo "  Created launcher at $LAUNCHER"
fi
echo ""

# Create config template
echo "✓ Creating config template..."
CONFIG_FILE="$HERCULES_HOME/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'CONFIG_TEMPLATE'
{
  "model_dir": "~/Models",
  "auto_save": true,
  "auto_save_interval": 10,
  "theme": "dark",
  "verbose": false,
  "context_window_size": 10,
  "cache_responses": false,
  "default_temp": 0.7,
  "default_tokens": 256
}
CONFIG_TEMPLATE
    echo "  Created config at $CONFIG_FILE"
fi
echo ""

# Final instructions
echo "╔════════════════════════════════════════╗"
echo "║  Installation Complete!                ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Download GGUF models to: $MODELS_DIR"
echo "     From: https://huggingface.co/TheBloke"
echo ""
echo "  2. Run Hercules:"
echo "     python3 hercules.py"
echo ""
echo "  3. Configure:"
echo "     Edit: $HERCULES_HOME/config.json"
echo ""
echo "Useful commands:"
echo "  /help      - Show all commands"
echo "  /setup     - Select model"
echo "  /hagent    - 3-layer agent hierarchy"
echo "  /code      - Claude Code patterns"
echo ""
echo "Documentation:"
echo "  README.md - Overview"
echo "  SUBAGENTS_GGUF_GUIDE.md - Detailed guide"
echo ""
