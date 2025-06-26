"""SmartifyTV integration."""
from __future__ import annotations

import logging
import voluptuous as vol
import asyncio
import aiofiles
import time
import json
import os
import broadlink as blk

from pathlib import Path
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_registry import async_get
from homeassistant.components.media_player import (
    MediaType,
    MediaPlayerState,
    MediaPlayerEntity,
    MediaPlayerDeviceClass,
    MediaPlayerEntityFeature,
)
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, STATE_UNAVAILABLE

from .const import DOMAIN, DEFAULT_NAME, CONF_POWER_ENTITY, CONF_IR_REMOTE, COMMAND_NAMES, INTERCOMMAND_PAUSE

_LOGGER = logging.getLogger(__name__)

# Константа для порогового значения мощности
POWER_THRESHOLD = 10  # Пороговое значение мощности в ваттах

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up Easy TV media player from a config entry."""
    async_add_entities([SmartifyTVMediaPlayer(hass, entry)], update_before_add=True)

async def get_entity_info(hass, entity_id):
    """Возвращает информацию о платформе и unique_id для указанного entity_id из реестра."""
    # Получаем реестр сущностей
    entity_registry = async_get(hass)
    # Получаем запись для указанного entity_id
    entry = entity_registry.async_get(entity_id)
    # Если запись найдена, возвращаем платформу и unique_id
    if entry:
        return entry.platform, entry.unique_id
    return None, None

class SmartifyTVMediaPlayer(MediaPlayerEntity):
    """Representation of an Easy TV media player."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize the media player."""
        self.hass = hass
        self._state = STATE_OFF
        self._attr_state = MediaPlayerState.OFF
        self._config_entry = config_entry
        self._name = config_entry.data.get("name", DEFAULT_NAME)  # Извлекаем имя из config_entry
        self._unique_id = config_entry.data.get("unique_id")  # Извлекаем сохраненный unique_id
        self._power_entity = config_entry.data.get(CONF_POWER_ENTITY)
        self._ir_remote = config_entry.data.get(CONF_IR_REMOTE)
        self._ir_remote_known_types = {
            'broadlink': True,
        }
        self._ir_remote_mac = None  # MAC _ir_remote (если хоть одну команду учили)
        self._ir_remote_platform = None  # Платформа пульта
        self._ir_remote_cmd_file = None  # Путь к файлу команд _ir_remote (если хоть одну команду учили)
        self._is_unavailable = False
        self._is_mute = False  # Атрибут для хранения состояния звука
        self._volume_level = 0.2  # Начальный уровень громкости (от 0.0 до 1.0) - не учитывается))
        self._current_channel = 1  # Начальный канал
        self._last_command_time = 0
        self._button_aliases = {
            "0": "KEY_0",
            "1": "KEY_1",
            "2": "KEY_2",
            "3": "KEY_3",
            "4": "KEY_4",
            "5": "KEY_5",
            "6": "KEY_6",
            "7": "KEY_7",
            "8": "KEY_8",
            "9": "KEY_9"
        }
        self._learned_commands = None
        self._learning_locked = False
        # Подписываемся на изменения состояния
        # Включение/выключение
        self.hass.bus.async_listen(
            "state_changed",
            self._handle_power_state_change
        )
        # начальная настройка, связанная с получением данных используемых физических устройств
        hass.async_create_task(self.async_initialize())

    async def async_initialize(self):
        """Асинхронная настройка IR устройства."""
        platform, unique_id = await get_entity_info(self.hass, self._ir_remote)
        self._ir_remote_platform = platform.lower()
        self._ir_remote_mac = unique_id
        # BROADLINK
        if self._ir_remote_platform == 'broadlink':
            self._ir_remote_cmd_file = self._find_broadlink_file_by_mac(self._ir_remote_mac)
            # Читаем команды. Если файл- ок, будут команды, иначе - None
            self._learned_commands = await self._read_broadlink_commands(self._ir_remote_cmd_file)
        else:
            self._ir_remote_mac = None
        # Проверяем начальное состояние
        await self._update_power_state()

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        # return self._state
        return self._attr_state

    @property
    def device_class(self):
        """Return the class of this device."""
        return MediaPlayerDeviceClass.TV

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return "mdi:television-classic"

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return (
            MediaPlayerEntityFeature.TURN_ON |
            MediaPlayerEntityFeature.TURN_OFF |
            MediaPlayerEntityFeature.VOLUME_MUTE |
            MediaPlayerEntityFeature.VOLUME_STEP |
            MediaPlayerEntityFeature.PREVIOUS_TRACK |
            MediaPlayerEntityFeature.NEXT_TRACK |
            MediaPlayerEntityFeature.PLAY_MEDIA |
            MediaPlayerEntityFeature.PLAY |
            MediaPlayerEntityFeature.STOP |
            MediaPlayerEntityFeature.PAUSE
        )

    @property
    def unique_id(self):
        """Return a unique ID for this media player."""
        return self._unique_id

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "is_unavailable": self._is_unavailable, 
            "uuid": self._unique_id,
            "ir_platform": self._ir_remote_platform,
            "ir_mac": self._ir_remote_mac,
            "ir_file": self._ir_remote_cmd_file,
            "ir_cmd": self._learned_commands 
        }

    @property
    def is_volume_muted(self):
        """Return True if volume is muted."""
        return self._is_mute

    @property
    def volume_level(self):
        """Return the volume level of the media player (0.1)."""
        return self._volume_level

    @property
    def media_title(self):
        """Return the current channel."""
        return f"Channel {self._current_channel}"

    def _find_broadlink_file_by_mac(self, mac_address):
        """Ищем в /config/.storage файл Broadlink, с указаным MAC-адресом в имени"""
        # Определяем шаблон
        filename_mask = f"broadlink_remote_{mac_address}_codes"
        # Полное имя файла команд Broadlink
        broadlink_file = Path(__file__).parent.parent.parent / ".storage" / filename_mask
        if broadlink_file.is_file():
            return broadlink_file.absolute()
        return None  # Если файл не найден

    async def _read_broadlink_commands(self, bfile):
        """Читаем команды Broadlink"""
        unique_id_key = self._unique_id
        if bfile and bfile.is_file():
            async with aiofiles.open(bfile, mode='r') as command_file:
                file_content = await command_file.read()
                data = json.loads(file_content)
                # Ищем запись по UID
                if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict):
                    if unique_id_key in data['data']:
                        # Переписываем найденные коды
                        return data['data'][unique_id_key].copy()
        return None

    async def async_check_command_existence(self, key_to_check):
        """Асинхронно проверяет наличие ключа в self._learned_commands."""
        try:
            # Не проверяем платформу, т.к. команды всех платформ приведены к определённому типу,
            # но проверяем известность платформы для этой интеграции
            # (способ отсюда: https://ru.stackoverflow.com/questions/460207/%D0%95%D1%81%D1%82%D1%8C-%D0%BB%D0%B8-%D0%B2-python-%D0%BE%D0%BF%D0%B5%D1%80%D0%B0%D1%82%D0%BE%D1%80-switch-case)
            if self._ir_remote_known_types[self._ir_remote_platform]:
                # Если платформа IR известна - проверяем команды
                if isinstance(self._learned_commands, dict):
                    # self._learned_commands содержит команды
                    if key_to_check in self._learned_commands:
                        # Команда изучена
                        return True
                    else:
                        # Команда не изучена
                        return False
                else:
                    # self._learned_commands == None
                    return False
        except KeyError as e:
            # Если платформа IR не известна - возвращаем True, т.к. мы не умеем работать с этой платформой!
            return True

    async def async_update(self):
        """Fetch new state data for the media player."""
        # Возможно, вам все еще нужно периодическое обновление для других данных

# ===================================================================================

    async def _get_ir_status(self):
        """Get the IR status."""
        ir_state = self.hass.states.get(self._ir_remote)
        if ir_state and ir_state.state not in (None, "unknown", "unavailable"):
            return ir_state.state
        else:
            _LOGGER.warning("IR entity state is unavailable or unknown: %s", ir_state.state if ir_state else "None")
            return STATE_UNAVAILABLE

    async def _update_power_state(self):
        """Обновление состояния мощности."""
        state = self.hass.states.get(self._power_entity)
        if state is None:
            self._state = STATE_OFF
            self._attr_state = MediaPlayerState.OFF
            self._is_unavailable = True
            self.async_write_ha_state()
            return
        if state.state not in (None, "unknown", "unavailable"):
            try:
                power_value = float(state.state)
                if power_value > POWER_THRESHOLD:
                    self._state = STATE_ON
                    self._attr_state = MediaPlayerState.ON
                else:
                    self._state = STATE_OFF
                    self._attr_state = MediaPlayerState.OFF
            except ValueError:
                _LOGGER.warning("Invalid power value: %s", state.state)
                self._state = STATE_OFF
        else:
            _LOGGER.warning("Power entity state is unavailable or unknown: %s", state.state)
            self._state = STATE_OFF
        # Определяем доступность
        if state.state in (None, "unknown", "unavailable") or await self._get_ir_status() == STATE_UNAVAILABLE:
            self._is_unavailable = True
        else:
            self._is_unavailable = False
        self.async_write_ha_state()

    @callback
    async def _handle_power_state_change(self, event):
        """Обработчик изменения состояния мощности."""
        if event.data.get("entity_id") == self._power_entity:
            await self._update_power_state()

    async def async_turn_on(self):
        """Turn the media player on."""
        # Вызов сервиса remote.send_command
        if self._state == STATE_OFF:
            try:
                await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'POWER_ON'}))
            except ValueError:
                _LOGGER.warning("POWER_ON error value: %s", power_state.state)

    async def async_turn_off(self):
        """Turn the media player off."""
        # Вызов сервиса remote.send_command
        if self._state == STATE_ON:
            try:
                await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'POWER_OFF'}))
            except ValueError:
                _LOGGER.warning("POWER_OFF error value: %s", power_state.state)

# ===================================================================================

    async def handle_send_command(self, call: ServiceCall):
        """Handle the service call to send a command."""
        command = call.data.get("command")
        # Проверяем наличие ключа
        if await self.async_check_command_existence(command):
            # Вызов сервиса remote.send_command
            await self.hass.services.async_call(
                "remote",
                "send_command",
                {
                    "entity_id": self._ir_remote,
                    "device": self._unique_id,
                    "command": command,
                }
            )

    async def handle_learn_command(self, call: ServiceCall):
        """Handle the service call to learn a command."""
        if self._learning_locked:
            return None
        command = call.data.get("command")
        # Вызов сервиса remote.learn_command
        await self.hass.services.async_call(
            "remote",
            "learn_command",
            {
                "entity_id": self._ir_remote,
                "device": self._unique_id,
                "command": command,
            }
        )
        if self._ir_remote_platform == 'broadlink':
            self._learning_locked = True
            # Ждём 35 сек и считываем коды из файла broadlink
            await asyncio.sleep(35)
            await self._read_broadlink_commands(self._ir_remote_cmd_file)
            self._learning_locked = False

#======================================================================================================

    async def ensure_command_pause(self, last_command_time, pause_duration):
        """Ensure a pause between commands."""
        current_time = time.time()
        elapsed_time = current_time - last_command_time
        # Проверяем, прошло ли pause_duration секунд с момента последнего вызова
        if elapsed_time < pause_duration:
            await asyncio.sleep(pause_duration - elapsed_time)
        return time.time()  # Возвращаем обновлённое время последнего вызова

    async def async_mute_volume(self, mute: bool):
        """Mute or unmute the volume."""
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        self._is_mute = mute
        command = 'MUTE' if mute else 'UNMUTE'
        try:
            await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": command}))
            self.async_write_ha_state()  # Обновляем состояние после изменения
        except ValueError:
            _LOGGER.warning("%s error for %s", command, self._name)

    async def async_volume_up(self):
        """Increase the volume level."""
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Увеличиваем громкость
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'VOLUME_UP'}))
        if self._volume_level < 1.0:
            self._volume_level = min(1.0, self._volume_level + 0.1)
            self.async_write_ha_state()

    async def async_volume_down(self):
        """Decrease the volume level."""
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Уменьшаем громкость
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'VOLUME_DOWN'}))
        if self._volume_level > 0.0:
            self._volume_level = max(0.0, self._volume_level - 0.1)
            self.async_write_ha_state()

    async def async_media_previous_track(self):
        """Switch to the previous channel."""
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Отправляем команду для переключения на предыдущий канал
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'CHANNEL_DOWN'}))
        # Обновляем состояние, если это необходимо
        self.async_write_ha_state()

    async def async_media_next_track(self):
        """Switch to the next channel."""
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Отправляем команду для переключения на следующий канал
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'CHANNEL_UP'}))
        # Обновляем состояние, если это необходимо
        self.async_write_ha_state()

    async def set_channel(self, call: ServiceCall):
        """Set the TV to a specific channel."""
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Переключаем канал
        channel_number = call.data.get('channel_number')
        if 1 <= channel_number <= 999:
            self._current_channel = channel_number
            self.async_write_ha_state()
            for digit in str(channel_number):
                command = self._button_aliases[digit]  # Получаем команду из приватного словаря
                """Вызов функции с текущей командой"""
                await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": command}))
                # Пауза в INTERCOMMAND_PAUSE секунды между отправкой каждой команды
                await asyncio.sleep(INTERCOMMAND_PAUSE)

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """ Принимаем номер канала ТВ """
        if media_type == MediaType.CHANNEL:
            if not media_id.isnumeric():
                _LOGGER.warning("Channel must be numeric:  %s", media_id)
                return
            await self.set_channel(ServiceCall(self.hass,domain=None, service=None, data={"channel_number": int(media_id)}))
            return

        if media_type in [MediaType.URL, MediaType.APP]:
            return

        _LOGGER.warning("Invalid media type:  %s", media_type)

    async def async_media_play(self) -> None:
        """Send play command to media player."""
				# Проверяем состояние, если выключен - выход
        # Происходит потому, что нажатие кнопки при выключенном ТВ ведёт к отображению его как включенного
        if self._state == STATE_OFF:
            return
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Отправляем команду для начала/возобновления проигрывания
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'PLAY'}))
        # Set status
        self._attr_state = MediaPlayerState.PLAYING
        # Обновляем состояние, если это необходимо
        self.async_write_ha_state()

    async def async_media_play_pause(self) -> None:
        """Send pause command to media player."""
				# Проверяем состояние, если выключен - выход
        # Происходит потому, что нажатие кнопки при выключенном ТВ ведёт к отображению его как включенного
        if self._state == STATE_OFF:
            return
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        new_command = 'PAUSE' if self._attr_state == MediaPlayerState.PLAYING else 'PLAY'
        # Отправляем команду для приостановки воспроизведения
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": new_command}))
        # Set status
        if self._attr_state == MediaPlayerState.PLAYING:
            self._attr_state = MediaPlayerState.PAUSED
        else:
            self._attr_state = MediaPlayerState.PLAYING
        # Обновляем состояние, если это необходимо
        self.async_write_ha_state()
        _LOGGER.warning("Calling media_play_pause")

    async def async_media_pause(self) -> None:
        """Send pause command to media player."""
				# Проверяем состояние, если выключен - выход
        # Происходит потому, что нажатие кнопки при выключенном ТВ ведёт к отображению его как включенного
        if self._state == STATE_OFF:
            return
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Отправляем команду для приостановки воспроизведения
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'PAUSE'}))
        # Set status
        self._attr_state = MediaPlayerState.PAUSED
        # Обновляем состояние, если это необходимо
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Send stop command to media player."""
				# Проверяем состояние, если выключен - выход
        # Происходит потому, что нажатие кнопки при выключенном ТВ ведёт к отображению его как включенного
        if self._state == STATE_OFF:
            return
        # Ожидаем окончание выполнения предыдущей команды, если она была
        self._last_command_time = await self.ensure_command_pause(self._last_command_time, INTERCOMMAND_PAUSE)
        # Отправляем команду для остановки воспроизведения
        await self.handle_send_command(ServiceCall(self.hass,domain=None,service=None,data={"command": 'STOP'}))
        # Set status
        self._attr_state = MediaPlayerState.IDLE
        # Обновляем состояние, если это необходимо
        self.async_write_ha_state()
        _LOGGER.warning("media_stop")

#======================================================================================================

    async def async_added_to_hass(self):
        """Called when entity is added to hass."""
        # Регистрация сервиса
        self.hass.services.async_register(
            domain=self._name.replace(".", "_").replace(" ", "_").lower(),
            service="learn_command",
            service_func=self.handle_learn_command,
            schema=None  # Здесь можно добавить vol.Schema для валидации данных
        )

        # Регистрация сервиса для отправки команды
        self.hass.services.async_register(
            domain=self._name.replace(".", "_").replace(" ", "_").lower(),
            service="send_command",
            service_func=self.handle_send_command,
            schema=None  # Здесь можно добавить vol.Schema для валидации данных
        )
