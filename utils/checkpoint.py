"""Checkpoint management for resume capability."""

import json
import os
from config import settings


def save_checkpoint(state, checkpoint_file=None):
    """
    Save checkpoint state to file.

    Args:
        state: Dictionary containing checkpoint state
        checkpoint_file: Optional custom checkpoint file path
    """
    if checkpoint_file is None:
        checkpoint_file = settings.CHECKPOINT_FILE

    os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)

    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, default=str)


def load_checkpoint(checkpoint_file=None):
    """
    Load checkpoint state from file.

    Args:
        checkpoint_file: Optional custom checkpoint file path

    Returns:
        Dictionary containing checkpoint state, or None if no checkpoint exists
    """
    if checkpoint_file is None:
        checkpoint_file = settings.CHECKPOINT_FILE

    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    return None


def clear_checkpoint(checkpoint_file=None):
    """
    Remove checkpoint file.

    Args:
        checkpoint_file: Optional custom checkpoint file path
    """
    if checkpoint_file is None:
        checkpoint_file = settings.CHECKPOINT_FILE

    if os.path.exists(checkpoint_file):
        os.remove(checkpoint_file)
        print(f"✅ Checkpoint cleared: {checkpoint_file}")
