"""Tests for board detection logic."""
import pytest
from unittest.mock import patch

from custom_components.exaviz.board_detector import (
    BoardType,
    detect_board_type,
    detect_onboard_poe,
    detect_addon_boards,
    detect_all_poe_systems,
)


class TestNonBlockingDetection:
    """detect_addon_boards / detect_onboard_poe must not call iterdir()."""

    @pytest.mark.asyncio
    async def test_detect_addon_boards_no_iterdir(self):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                result = await detect_addon_boards()
                mock_iterdir.assert_not_called()
                assert result == []

    @pytest.mark.asyncio
    async def test_detect_onboard_poe_no_iterdir(self):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                result = await detect_onboard_poe()
                mock_iterdir.assert_not_called()
                assert result == []


class TestDetectAllPoeSystems:
    """End-to-end detection with sub-functions mocked."""

    @pytest.mark.asyncio
    async def test_cruiser_onboard_plus_two_addons(self):
        with patch("custom_components.exaviz.board_detector.detect_board_type", return_value=BoardType.CRUISER), \
             patch("custom_components.exaviz.board_detector.detect_onboard_poe", return_value=[f"poe{i}" for i in range(8)]), \
             patch("custom_components.exaviz.board_detector.detect_addon_boards", return_value=["pse0", "pse1"]):
            result = await detect_all_poe_systems()

        assert result["board_type"] == BoardType.CRUISER
        assert len(result["onboard_ports"]) == 8
        assert len(result["addon_boards"]) == 2
        assert result["total_poe_ports"] == 24

    @pytest.mark.asyncio
    async def test_interceptor_clears_onboard(self):
        """Interceptor's poe interfaces belong to add-on boards."""
        with patch("custom_components.exaviz.board_detector.detect_board_type", return_value=BoardType.INTERCEPTOR), \
             patch("custom_components.exaviz.board_detector.detect_onboard_poe", return_value=[f"poe{i}" for i in range(8)]), \
             patch("custom_components.exaviz.board_detector.detect_addon_boards", return_value=["pse0", "pse1"]):
            result = await detect_all_poe_systems()

        assert result["board_type"] == BoardType.INTERCEPTOR
        assert len(result["onboard_ports"]) == 0
        assert len(result["addon_boards"]) == 2
        assert result["total_poe_ports"] == 16

    @pytest.mark.asyncio
    async def test_cruiser_onboard_only(self):
        with patch("custom_components.exaviz.board_detector.detect_board_type", return_value=BoardType.CRUISER), \
             patch("custom_components.exaviz.board_detector.detect_onboard_poe", return_value=[f"poe{i}" for i in range(8)]), \
             patch("custom_components.exaviz.board_detector.detect_addon_boards", return_value=[]):
            result = await detect_all_poe_systems()

        assert result["total_poe_ports"] == 8
        assert len(result["addon_boards"]) == 0

    @pytest.mark.asyncio
    async def test_no_poe_systems(self):
        with patch("custom_components.exaviz.board_detector.detect_board_type", return_value=BoardType.UNKNOWN), \
             patch("custom_components.exaviz.board_detector.detect_onboard_poe", return_value=[]), \
             patch("custom_components.exaviz.board_detector.detect_addon_boards", return_value=[]):
            result = await detect_all_poe_systems()

        assert result["total_poe_ports"] == 0
