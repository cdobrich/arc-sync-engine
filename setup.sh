#!/bin/sh

set -e

PROJECT_DIR=$(cd "$(dirname "$0")" && pwd)
VENV_DIR="$PROJECT_DIR/.venv"
PYPROJECT_FILE="$PROJECT_DIR/pyproject.toml"

# Verify pyproject.toml exists before proceeding
if [ ! -f "$PYPROJECT_FILE" ]; then
  echo "Error: $PYPROJECT_FILE not found."
  exit 1
fi

# Check if a virtual environment already exists
if [ -d "$VENV_DIR" ]; then
  echo "Virtual environment already exists in $VENV_DIR."
  echo "What would you like to do?"
  echo "1) Delete current .venv and create a new one"
  echo "2) Use existing .venv"
  read -p "Enter your choice (1 or 2): " choice

  case "$choice" in
    1)
      echo "Deleting existing virtual environment..."
      rm -rf "$VENV_DIR"
      echo "Creating new virtual environment in $VENV_DIR..."
      python3 -m venv "$VENV_DIR"
      ;;
    2)
      echo "Using existing virtual environment."
      ;;
    *)
      echo "Invalid choice. Exiting."
      exit 1
      ;;
  esac
else
  echo "Creating virtual environment in $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi

# Activate the virtual environment
if [ -f "$VENV_DIR/bin/activate" ]; then
  . "$VENV_DIR/bin/activate"
else
  echo "Error: Virtual environment activation script not found at $VENV_DIR/bin/activate"
  exit 1
fi

echo "Upgrading pip and build tools..."
pip install --upgrade pip setuptools wheel

# Check if "dev" argument was passed
if [ "$1" = "dev" ]; then
  echo "Installing project dependencies with dev extras from pyproject.toml..."
  pip install -e "$PROJECT_DIR[dev]"
else
  echo "Installing project dependencies from pyproject.toml..."
  pip install -e "$PROJECT_DIR[sync]"
fi

echo ""
echo "Setup complete!"
echo "To activate the virtual environment, run:"
echo "   source $VENV_DIR/bin/activate"
echo "or"
echo "   . $VENV_DIR/bin/activate"
echo ""
echo "To deactivate, run:"
echo "  deactivate"