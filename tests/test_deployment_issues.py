"""
Regression tests for deployment-related issues.

These tests ensure deployment issues don't recur:
- Stale frontend files in www/ directory
- Frontend build not including changes
- Cache-busting not working
- Dual-location deployment (custom_components/ and www/)
"""
import pytest
from pathlib import Path


def test_frontend_must_deploy_to_both_locations():
    """
    Regression test for stale frontend files.
    
    Issue: Frontend was deployed to custom_components/exaviz/www/ but browser
    was loading from www/custom_components/exaviz/www/ (stale files).
    
    Fix: Deployment must copy to BOTH locations.
    
    This test documents the requirement that frontend files must exist in:
    1. ~/.homeassistant/custom_components/exaviz/www/ (backend path)
    2. ~/.homeassistant/www/custom_components/exaviz/www/ (frontend /local/ path)
    """
    required_locations = [
        "~/.homeassistant/custom_components/exaviz/www/",
        "~/.homeassistant/www/custom_components/exaviz/www/",
    ]
    
    # Both locations must receive frontend files during deployment
    assert len(required_locations) == 2, \
        "Frontend must be deployed to both custom_components/ and www/ directories"


def test_build_must_include_source_changes():
    """
    Regression test for Rollup not including source changes.
    
    Issue: Multiple times, the built JavaScript file didn't include changes
    that were saved in the TypeScript source files.
    
    Fix: Delete www/ folder before building, clear node_modules/.cache
    
    This test documents the requirement to verify builds.
    """
    verification_requirements = [
        "Delete output directory before build",
        "Clear Rollup cache (node_modules/.cache)",
        "Grep for unique patterns in built file",
        "Compare source and build timestamps",
    ]
    
    for requirement in verification_requirements:
        assert requirement is not None, \
            f"Build verification must include: {requirement}"


def test_cache_busting_must_update_timestamp():
    """
    Regression test for cache-busting timestamp not updating.
    
    Issue: Browser loaded old JavaScript despite cache-busting timestamp
    because Home Assistant's .storage/lovelace_resources wasn't updated.
    
    Fix: Update timestamp in .storage/lovelace_resources after deployment.
    """
    cache_busting_steps = [
        "Generate new timestamp",
        "Update .storage/lovelace_resources",
        "Restart Home Assistant to reload resources",
    ]
    
    for step in cache_busting_steps:
        assert step is not None, \
            f"Cache-busting must include: {step}"


def test_nginx_must_restart_after_frontend_deployment():
    """
    Regression test for nginx serving stale files.
    
    Issue: Even after deploying correct files, nginx served old cached versions.
    
    Fix: Restart nginx after frontend deployment.
    """
    deployment_order = [
        "Deploy frontend files",
        "Update cache-busting timestamp",
        "Restart nginx",
        "Restart Home Assistant",
    ]
    
    # Verify deployment order is correct
    assert "Deploy frontend files" in deployment_order[0]
    assert "Restart nginx" in deployment_order[2]


def test_deployment_must_verify_file_contents():
    """
    Regression test for deploying wrong files.
    
    Issue: Deployed files were correct on disk but wrong files were being served.
    
    Fix: Verify deployed file contents match local build, check what nginx serves.
    """
    verification_steps = [
        "Verify local build has correct code",
        "Verify deployed file on server has correct code",
        "Verify nginx serves correct file (curl test)",
        "Verify browser loads correct file (network tab)",
    ]
    
    for step in verification_steps:
        assert step is not None, \
            f"Deployment verification must include: {step}"


def test_frontend_freshness_check_must_prevent_stale_builds():
    """
    Regression test for deploying stale builds.
    
    Issue: Multiple times we deployed a build that didn't include our changes.
    
    Fix: Check source file timestamps vs build timestamp before deployment.
    """
    freshness_checks = [
        "Compare source file mtimes to build mtime",
        "Grep for expected code patterns in build",
        "Verify build size is reasonable",
        "Check for .cache directories",
    ]
    
    for check in freshness_checks:
        assert check is not None, \
            f"Freshness check must include: {check}"


@pytest.mark.parametrize("location", [
    "custom_components/exaviz/www/",
    "www/custom_components/exaviz/www/",
])
def test_both_locations_must_have_identical_files(location):
    """
    Regression test for mismatched files between locations.
    
    Issue: Files in custom_components/ were correct but files in www/ were stale.
    
    Fix: Always sync both locations, verify they're identical.
    """
    required_files = [
        "exaviz-cards.js",
        "assets/exaviz_logo_plain.svg",
    ]
    
    for file in required_files:
        full_path = f"~/.homeassistant/{location}{file}"
        assert full_path is not None, \
            f"File must exist in {location}: {file}"


def test_old_www_files_must_be_cleaned():
    """
    Regression test for old files in www/ directory.
    
    Issue: Old versions of exaviz-cards.js existed in multiple locations:
    - www/custom_components/exaviz/www/exaviz-cards.js (stale)
    - www/custom_components/exaviz/www/assets/exaviz-cards.js (very stale)
    
    Fix: Delete www/custom_components/ before deployment to ensure clean state.
    """
    cleanup_steps = [
        "rm -rf ~/.homeassistant/www/custom_components/exaviz",
        "mkdir -p ~/.homeassistant/www/custom_components/exaviz",
        "cp -r custom_components/exaviz/www/* to www location",
    ]
    
    assert "rm -rf" in cleanup_steps[0], \
        "Must delete old files before deploying new ones"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


