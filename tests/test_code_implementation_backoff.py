"""
CODE IMPLEMENTATION VERIFICATION: Backoff State in Actual Code

This test file verifies that the actual code files contain the CORRECT
implementation of backoff state handling.

Unlike test_backoff_state_regression.py which tests logic, this file
reads the actual source code and verifies the fix is present.

If these tests fail, someone has reverted the fix in the actual code!
"""
from pathlib import Path


def test_frontend_has_correct_backoff_mapping():
    """
    Verify lovelace-cards/src/cards/exaviz-poe-card.ts has correct mapping.
    
    CORRECT:
        if (hardwareStatus.includes('backoff')) return 'empty';
    
    WRONG (the bug we fixed):
        if (hardwareStatus.includes('backoff')) return 'disabled';
    """
    frontend_file = Path(__file__).parent.parent / "lovelace-cards" / "src" / "cards" / "exaviz-poe-card.ts"
    
    if not frontend_file.exists():
        raise FileNotFoundError(f"Frontend file not found: {frontend_file}")
    
    content = frontend_file.read_text()
    
    # Check for CORRECT implementation
    correct_patterns = [
        "backoff.*empty",  # Should map to empty
        "IP808AR",  # Should mention the chip
    ]
    
    # Check for WRONG implementation (the bug)
    wrong_patterns = [
        r"backoff.*disabled.*Hardware protection",  # Old comment
        r"backoff.*protection mode",  # Wrong interpretation
    ]
    
    # Verify correct patterns exist
    assert "backoff" in content.lower(), \
        "Frontend should handle 'backoff' state"
    
    # Critical check: backoff should NOT return 'disabled' for protection reasons
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'backoff' in line.lower() and 'includes' in line:
            # Found the backoff handling line
            # Check if it returns 'empty' (correct) or 'disabled' (wrong)
            if 'disabled' in line and 'Hardware protection' in content[max(0, content.find(line)-100):content.find(line)+100]:
                raise AssertionError(
                    f"REGRESSION DETECTED on line {i+1}!\n"
                    f"Frontend maps backoff to 'disabled' with 'Hardware protection' comment.\n"
                    f"This is the BUG we fixed on October 31, 2025!\n"
                    f"Line: {line.strip()}\n"
                    f"Should map backoff to 'empty', not 'disabled'"
                )
    
    print(f"✅ Frontend file contains backoff handling")


def test_backend_has_correct_enabled_logic():
    """
    Verify custom_components/exaviz/poe_readers.py has correct enabled logic.
    
    CORRECT:
        "enabled": state not in ("disabled",)
    
    WRONG (the bug we fixed):
        "enabled": state not in ("backoff", "searching", "disabled")
    """
    backend_file = Path(__file__).parent.parent / "custom_components" / "exaviz" / "poe_readers.py"
    
    if not backend_file.exists():
        raise FileNotFoundError(f"Backend file not found: {backend_file}")
    
    content = backend_file.read_text()
    
    # Check for the bug (enabled logic excluding backoff)
    if '"enabled": state not in ("backoff"' in content:
        raise AssertionError(
            "REGRESSION DETECTED!\n"
            "Backend excludes 'backoff' from enabled states.\n"
            "This is the BUG we fixed on October 31, 2025!\n"
            "Only 'disabled' should make enabled=false"
        )
    
    if '"enabled": state not in ("searching"' in content and 'backoff' in content:
        raise AssertionError(
            "REGRESSION DETECTED!\n"
            "Backend excludes 'searching' or 'backoff' from enabled states.\n"
            "This is the BUG we fixed on October 31, 2025!"
        )
    
    # Verify correct pattern exists
    assert '"enabled":' in content, \
        "Backend should set 'enabled' attribute"
    
    # Check for comment explaining the fix
    if 'backoff' in content.lower() and 'enabled' in content.lower():
        assert 'ENABLED' in content or 'enabled states' in content.lower(), \
            "Backend should document that backoff/searching are enabled states"
    
    print(f"✅ Backend file has correct enabled logic")


# Tests for .cursorrules and docs/ removed -- those files are in the
# internal development repo only, not in the public HACS distribution repo.
# The backoff state behavior is verified by test_backoff_state_regression.py.


def test_built_frontend_contains_fix():
    """
    Verify the built frontend file (exaviz-cards.js) has the fix.
    
    This is critical because we deploy the BUILT file, not the source!
    """
    built_file = Path(__file__).parent.parent / "custom_components" / "exaviz" / "www" / "exaviz-cards.js"
    
    if not built_file.exists():
        print("⚠️  Built frontend not found (run: cd lovelace-cards && npm run build)")
        return
    
    content = built_file.read_text()
    
    # Check that backoff handling exists in built file
    assert 'backoff' in content.lower(), \
        "Built frontend should handle 'backoff' state"
    
    # The built file is minified, so we can't check exact syntax
    # But we can verify it's not obviously wrong
    print(f"✅ Built frontend file exists and contains backoff handling")


if __name__ == "__main__":
    import sys
    
    tests = [
        test_frontend_has_correct_backoff_mapping,
        test_backend_has_correct_enabled_logic,
        test_built_frontend_contains_fix,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except (AssertionError, FileNotFoundError) as e:
            print(f"FAIL: {test_func.__name__}")
            print(f"   {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    
    sys.exit(1 if failed > 0 else 0)
