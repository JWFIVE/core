"""BleBox climate entity."""

from datetime import timedelta
from typing import Any

import blebox_uniapi.climate

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BleBoxConfigEntry
from .entity import BleBoxEntity

SCAN_INTERVAL = timedelta(seconds=5)

BLEBOX_TO_HVACMODE = {
    0: HVACMode.OFF,
    1: HVACMode.HEAT,
    2: HVACMode.COOL,
}

BLEBOX_TO_HVACACTION = {
    0: HVACAction.IDLE,
    1: HVACAction.HEATING,
    2: HVACAction.COOLING,
    3: HVACAction.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BleBoxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a BleBox climate entity."""
    entities = [
        BleBoxClimateEntity(feature)
        for feature in config_entry.runtime_data.features.get("climates", [])
    ]
    async_add_entities(entities, True)


class BleBoxClimateEntity(BleBoxEntity[blebox_uniapi.climate.Climate], ClimateEntity):
    """Representation of a BleBox climate feature (saunaBox)."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return list of supported HVAC modes."""
        if self._feature.mode is None:
            return [HVACMode.OFF]
        return [HVACMode.OFF, BLEBOX_TO_HVACMODE[self._feature.mode]]

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the desired HVAC mode."""
        if self._feature.is_on is None:
            return None
        if not self._feature.is_on:
            return HVACMode.OFF
        if self._feature.mode is not None:
            return BLEBOX_TO_HVACMODE[self._feature.mode]
        return HVACMode.HEAT if self._feature.is_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the actual current HVAC action."""
        if self._feature.hvac_action is not None:
            if not self._feature.is_on:
                return HVACAction.OFF
            return BLEBOX_TO_HVACACTION[self._feature.hvac_action]
        if not (is_on := self._feature.is_on):
            return None if is_on is None else HVACAction.OFF

        # NOTE: In practice, there's no need to handle case when is_heating is None
        return HVACAction.HEATING if self._feature.is_heating else HVACAction.IDLE

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature supported."""
        return self._feature.max_temp

    @property
    def min_temp(self) -> float:
        """Return the maximum temperature supported."""
        return self._feature.min_temp

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._feature.current

    @property
    def target_temperature(self) -> float | None:
        """Return the desired thermostat temperature."""
        return self._feature.desired

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the climate entity mode."""
        if hvac_mode in [HVACMode.HEAT, HVACMode.COOL]:
            await self._feature.async_on()
            return

        await self._feature.async_off()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the thermostat temperature."""
        value = kwargs[ATTR_TEMPERATURE]
        await self._feature.async_set_temperature(value)
