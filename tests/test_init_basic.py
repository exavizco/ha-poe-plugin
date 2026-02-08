"""Basic tests for __init__.py module.

Tests the simpler parts of the integration entry point.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from homeassistant.const import Platform

# Import the module to test constants and basic structure
import custom_components.exaviz as exaviz_init


class TestConstants:
    """Test module constants."""

    def test_platforms_constant(self):
        """Test PLATFORMS constant exists and has correct PoE platforms."""
        assert hasattr(exaviz_init, 'PLATFORMS')
        assert len(exaviz_init.PLATFORMS) == 4  # sensor, switch, binary_sensor, button
        assert 'sensor' in exaviz_init.PLATFORMS
        assert 'switch' in exaviz_init.PLATFORMS
        assert 'binary_sensor' in exaviz_init.PLATFORMS
        assert 'button' in exaviz_init.PLATFORMS

    def test_logger_exists(self):
        """Test that logger is properly initialized."""
        assert hasattr(exaviz_init, '_LOGGER')
        assert exaviz_init._LOGGER.name == 'custom_components.exaviz'


class TestAsyncReloadEntry:
    """Test async_reload_entry function."""

    @pytest.mark.asyncio
    async def test_async_reload_entry(self):
        """Test async_reload_entry calls unload and setup."""
        mock_hass = Mock()
        mock_entry = Mock()
        
        # Mock the functions that reload calls
        with patch.object(exaviz_init, 'async_unload_entry', new_callable=AsyncMock) as mock_unload:
            with patch.object(exaviz_init, 'async_setup_entry', new_callable=AsyncMock) as mock_setup:
                await exaviz_init.async_reload_entry(mock_hass, mock_entry)
                
                # Verify both functions were called with correct arguments
                mock_unload.assert_called_once_with(mock_hass, mock_entry)
                mock_setup.assert_called_once_with(mock_hass, mock_entry)


class TestModuleStructure:
    """Test module structure and imports."""

    def test_required_imports_exist(self):
        """Test that required imports are available."""
        # Test that key classes/functions are imported
        assert hasattr(exaviz_init, 'async_setup_entry')
        assert hasattr(exaviz_init, 'async_unload_entry')
        assert hasattr(exaviz_init, 'async_reload_entry')
        
        # Test that these are callable
        assert callable(exaviz_init.async_setup_entry)
        assert callable(exaviz_init.async_unload_entry)
        assert callable(exaviz_init.async_reload_entry)

    def test_domain_import(self):
        """Test that DOMAIN is properly imported."""
        # We can't directly test the import due to mocking, but we can test
        # that the module structure is correct
        assert hasattr(exaviz_init, 'DOMAIN')


class TestAsyncSetupEntryBasic:
    """Test basic aspects of async_setup_entry without full mocking."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_coordinator_creation(self):
        """Test that async_setup_entry creates coordinator."""
        mock_hass = Mock()
        mock_entry = Mock()
        
        # Mock the coordinator class
        with patch('custom_components.exaviz.ExavizDataUpdateCoordinator') as mock_coordinator_class:
            mock_coordinator = AsyncMock()
            mock_coordinator.async_setup.return_value = False  # Simulate setup failure
            mock_coordinator_class.return_value = mock_coordinator
            
            # Should raise ConfigEntryNotReady when coordinator setup fails
            with pytest.raises(Exception):  # ConfigEntryNotReady is mocked
                await exaviz_init.async_setup_entry(mock_hass, mock_entry)
            
            # Verify coordinator was created with correct arguments
            mock_coordinator_class.assert_called_once_with(mock_hass, mock_entry)
            mock_coordinator.async_setup.assert_called_once()


class TestAsyncUnloadEntryBasic:
    """Test basic aspects of async_unload_entry without full mocking."""

    @pytest.mark.asyncio
    async def test_async_unload_entry_platforms_unload(self):
        """Test that async_unload_entry attempts to unload platforms."""
        mock_hass = Mock()
        mock_entry = Mock()
        
        # Mock the config_entries.async_unload_platforms to return False (failure)
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        
        # Mock hass.data structure
        mock_hass.data = {'exaviz': {}}
        
        result = await exaviz_init.async_unload_entry(mock_hass, mock_entry)
        
        # Should return False when platform unload fails
        assert result is False
        
        # Verify async_unload_platforms was called with correct arguments
        mock_hass.config_entries.async_unload_platforms.assert_called_once_with(
            mock_entry, exaviz_init.PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_async_unload_entry_success_path(self):
        """Test successful unload path."""
        mock_hass = Mock()
        mock_entry = Mock()
        mock_entry.entry_id = "test_entry"
        
        # Mock successful platform unload
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        
        # Mock coordinator with async_shutdown method
        mock_coordinator = AsyncMock()
        mock_coordinator.async_shutdown = AsyncMock()
        
        # Mock hass.data structure with coordinator
        mock_hass.data = {
            'exaviz': {
                'test_entry': mock_coordinator
            }
        }
        
        # Mock services
        mock_hass.services = Mock()
        
        # Mock async_unload_services
        with patch('custom_components.exaviz.async_unload_services', new_callable=AsyncMock) as mock_unload_services:
            result = await exaviz_init.async_unload_entry(mock_hass, mock_entry)
            
            # Should return True on success
            assert result is True
            
            # Verify coordinator was removed from hass.data
            assert 'test_entry' not in mock_hass.data['exaviz']
            
            # Verify coordinator shutdown was called
            mock_coordinator.async_shutdown.assert_called_once()
            
            # Verify services were unloaded (since hass.data[DOMAIN] is now empty)
            mock_unload_services.assert_called_once_with(mock_hass) 