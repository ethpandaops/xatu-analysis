"""Validator pubkey parsing and validation utilities."""
import re
from typing import List, Tuple, Optional


def validate_pubkey(pubkey: str) -> bool:
    """Validate Ethereum validator pubkey format (0x + 96 hex chars).
    
    Args:
        pubkey: The pubkey string to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Remove 0x prefix if present
    clean = pubkey.lower().strip()
    if clean.startswith('0x'):
        clean = clean[2:]
    
    # Check if it's exactly 96 hex characters
    if len(clean) != 96:
        return False
    
    # Check if all characters are valid hex
    try:
        int(clean, 16)
        return True
    except ValueError:
        return False


def clean_pubkey(pubkey: str) -> Optional[str]:
    """Clean and normalize a pubkey, return None if invalid.
    
    Args:
        pubkey: The raw pubkey string
        
    Returns:
        Normalized pubkey with 0x prefix, or None if invalid
    """
    # Strip whitespace
    clean = pubkey.strip()
    
    # Skip empty lines
    if not clean:
        return None
    
    # Normalize to lowercase
    clean = clean.lower()
    
    # Ensure 0x prefix
    if not clean.startswith('0x'):
        clean = '0x' + clean
    
    # Validate and return
    if validate_pubkey(clean):
        return clean
    return None


def parse_validator_pubkeys(raw_input: str) -> Tuple[List[str], List[str]]:
    """Parse newline-separated validator pubkeys, return (valid_pubkeys, errors).
    
    Args:
        raw_input: Multi-line string containing validator pubkeys
        
    Returns:
        Tuple of (list of valid pubkeys, list of error messages)
    """
    valid_pubkeys = []
    errors = []
    
    # Split by newlines and process each line
    lines = raw_input.strip().split('\n')
    
    for i, line in enumerate(lines, 1):
        # Skip empty lines
        if not line.strip():
            continue
            
        # Try to clean and validate
        cleaned = clean_pubkey(line)
        if cleaned:
            valid_pubkeys.append(cleaned)
        else:
            errors.append(f"Line {i}: Invalid pubkey format '{line.strip()}'")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_pubkeys = []
    for pubkey in valid_pubkeys:
        if pubkey not in seen:
            seen.add(pubkey)
            unique_pubkeys.append(pubkey)
    
    # Add note about duplicates if any were removed
    if len(valid_pubkeys) > len(unique_pubkeys):
        duplicate_count = len(valid_pubkeys) - len(unique_pubkeys)
        errors.append(f"Removed {duplicate_count} duplicate pubkey(s)")
    
    return unique_pubkeys, errors


def format_pubkey_for_display(pubkey: str, max_length: int = 20) -> str:
    """Format pubkey for UI display (e.g., '0x1234...abcd').
    
    Args:
        pubkey: The full pubkey to format
        max_length: Maximum display length (minimum 10)
        
    Returns:
        Formatted pubkey string
    """
    if max_length < 10:
        max_length = 10
        
    if len(pubkey) <= max_length:
        return pubkey
    
    # Calculate prefix and suffix lengths
    # Reserve 3 characters for '...'
    remaining = max_length - 3
    prefix_len = (remaining + 1) // 2  # Slightly favor prefix if odd
    suffix_len = remaining - prefix_len
    
    return f"{pubkey[:prefix_len]}...{pubkey[-suffix_len:]}"


def get_validator_summary_text(pubkeys: List[str]) -> str:
    """Generate summary text for validator selection.
    
    Args:
        pubkeys: List of validator pubkeys
        
    Returns:
        Human-readable summary text
    """
    count = len(pubkeys)
    
    if count == 0:
        return "No validators selected"
    elif count == 1:
        return f"1 validator selected: {format_pubkey_for_display(pubkeys[0])}"
    elif count <= 3:
        formatted = [format_pubkey_for_display(pk) for pk in pubkeys]
        return f"{count} validators selected: {', '.join(formatted)}"
    else:
        # Show first two and last one
        first_two = [format_pubkey_for_display(pk) for pk in pubkeys[:2]]
        last_one = format_pubkey_for_display(pubkeys[-1])
        return f"{count} validators selected: {', '.join(first_two)}, ... {last_one}"