"""Repair flows for the Emerald Hot Water System integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import AWSCRT_STRADDLE_ISSUE_ID


class AwscrtStraddleRepairFlow(RepairsFlow):
    """One-click restart: the only fix for a stuck awscrt version straddle.

    See is_awscrt_straddle_error in helpers.py for why nothing short of
    restarting the process can clear this.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm and trigger the restart."""
        if user_input is not None:
            await self.hass.services.async_call(
                "homeassistant", "restart", blocking=False
            )
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Return the repair flow for the given issue id."""
    if issue_id == AWSCRT_STRADDLE_ISSUE_ID:
        return AwscrtStraddleRepairFlow()
    raise ValueError(f"Unknown issue id: {issue_id}")
