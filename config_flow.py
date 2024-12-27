"""Config flow for SmartifyTV integration."""
from __future__ import annotations

import logging
import uuid
import voluptuous as vol
from typing import Any
#from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME

from .const import DOMAIN, CONF_POWER_ENTITY, CONF_IR_REMOTE, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    # Проверяем, существует ли выбранная сущность
    if not hass.states.get(data[CONF_POWER_ENTITY]):
        raise InvalidPowerEntity(f"Power entity {data[CONF_POWER_ENTITY]} is invalid or does not exist.")

    if not hass.states.get(data[CONF_IR_REMOTE]):
        raise InvalidIREntity(f"IR remote entity {data[CONF_IR_REMOTE]} is invalid or does not exist.")

    return {"title": data[CONF_NAME]}

class SmartifyTVConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartifyTV."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Добавляем префикс к имени устройства
            #user_input['name'] = f"{DOMAIN}_{user_input['name']}"

            # Проверим комплект розетка-пульт и не даём создать дубликат такого набора
            if self._entry_exists(user_input[CONF_POWER_ENTITY], user_input[CONF_IR_REMOTE]):
                errors["base"] = "device_exists"
            else:

                # Генерация уникального идентификатора
                #unique_id = f"{DOMAIN}_{user_input[CONF_NAME]}_{user_input[CONF_POWER_ENTITY]}"
                # Делаем UUID по-другому: используем постоянный идентификатор для уникального ID
                unique_id = f"{DOMAIN}_{uuid.uuid4().hex}"
                unique_id = unique_id.replace("-", "").replace(".", "_").replace(" ", "_").lower()
                # Добавляем UUID к набору введённых данных
                user_input["unique_id"] = unique_id

                try:
                    info = await validate_input(self.hass, user_input)
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],  # Use the user-provided name for the device
                        data=user_input
                    )
                except InvalidPowerEntity as e:
                    _LOGGER.error(e)
                    errors["base"] = "invalid_power_entity"
                except InvalidIREntity as e:
                    _LOGGER.error(e)
                    errors["base"] = "invalid_ir_entity"
                except Exception as ex:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception: %s", ex)
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,  # Allow user to set device name
                    vol.Required(CONF_POWER_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=['sensor'],
                            device_class=['power']
                        ),
                    ),
                    vol.Required(CONF_IR_REMOTE): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=['remote']
                        ),
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return SmartifyTVOptionsFlow(config_entry)

    @callback
    def _entry_exists(self, power_entity, ir_remote):
        """Check if an entry with the same power_entity and ir_remote exists."""
        for entry in self._async_current_entries():
            if (entry.data.get(CONF_POWER_ENTITY) == power_entity and
                    entry.data.get(CONF_IR_REMOTE) == ir_remote):
                return True
        return False


class SmartifyTVOptionsFlow(OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        #self.config_entry = config_entry
        self.entry_id = config_entry.entry_id  # Сохраняем только entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""

        config_entry = self.hass.config_entries.async_get_entry(self.entry_id)
        # Используйте config_entry для управления опциями

        errors = {}

        if user_input is not None:
            try:
                # Проверяем существование новых сущностей
                if not self.hass.states.get(user_input[CONF_POWER_ENTITY]):
                    raise InvalidPowerEntity(f"Power entity {user_input[CONF_POWER_ENTITY]} is invalid or does not exist.")

                if not self.hass.states.get(user_input[CONF_IR_REMOTE]):
                    raise InvalidIREntity(f"IR remote entity {user_input[CONF_IR_REMOTE]} is invalid or does not exist.")

                # Проверяем, существует ли уже запись с такими же параметрами
                if self._entry_exists(user_input[CONF_POWER_ENTITY], user_input[CONF_IR_REMOTE]):
                    errors["base"] = "device_exists"
                else:
                    # Создаем новый словарь с данными
                    new_data = {
                        "unique_id": config_entry.data["unique_id"],  # Preserve unique_id
                        CONF_NAME: config_entry.data[CONF_NAME],
                        CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
                        CONF_IR_REMOTE: user_input[CONF_IR_REMOTE],
                    }

                    # Обновляем entry
                    self.hass.config_entries.async_update_entry(
                        config_entry,
                        data=new_data,
                    )

                    # Перезагружаем entry
                    await self.hass.config_entries.async_reload(config_entry.entry_id)

                    return self.async_create_entry(title="", data=None)

            except InvalidPowerEntity as e:
                _LOGGER.error(e)
                errors["base"] = "invalid_power_entity"
            except InvalidIREntity as e:
                _LOGGER.error(e)
                errors["base"] = "invalid_ir_entity"
            except Exception as ex:
                _LOGGER.exception("Unexpected exception: %s", ex)
                errors["base"] = "unknown"

        # Используем get для безопасного доступа к данным конфигурации
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POWER_ENTITY, default=config_entry.data.get(CONF_POWER_ENTITY)): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=['sensor'],
                            device_class=['power']
                        ),
                    ),
                    vol.Required(CONF_IR_REMOTE, default=config_entry.data.get(CONF_IR_REMOTE, "")): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=['remote']
                        ),
                    ),
                }
            ),
            errors=errors,
        )

    @callback
    def _entry_exists(self, power_entity, ir_remote):
        """Check if an entry with the same power_entity and ir_remote exists."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id != self.entry_id and \
               entry.data.get(CONF_POWER_ENTITY) == power_entity and \
               entry.data.get(CONF_IR_REMOTE) == ir_remote:
                return True
        return False


class InvalidPowerEntity(HomeAssistantError):
    """Error to indicate there is an invalid power entity."""
    def __init__(self, message: str) -> None:
        super().__init__(message)

class InvalidIREntity(HomeAssistantError):
    """Error to indicate there is an invalid IR entity."""
    def __init__(self, message: str) -> None:
        super().__init__(message)