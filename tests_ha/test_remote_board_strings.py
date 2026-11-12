"""#43: board-supplied text shown on Board Status is trimmed and capped."""
from __future__ import annotations

from tests.fake_board import case

from .test_remote_runtime import setup_remote, state

CAP = 256


async def test_long_board_text_is_capped_on_board_status(hass, board):
    reply = case("board")
    reply["body"]["os_version"] = "x" * 500_000
    reply["body"]["kernel_version"] = "  6.18.34  "
    reply["body"]["netplan_version"] = {"nested": "y" * 100_000}
    board.reply("GET", "/board", reply)
    await setup_remote(hass, board)

    attrs = state(hass, "sensor.board_status").attributes
    assert attrs["os_version"] == "x" * CAP
    assert attrs["kernel_version"] == "6.18.34"
    assert "netplan_version" not in attrs
    # Fields the board sent normally are untouched.
    assert attrs["board_serial"] == "CRU-TEST-0001"
