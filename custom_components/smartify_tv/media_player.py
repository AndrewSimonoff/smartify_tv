"""SmartifyTV integration."""
from __future__ import annotations

import logging
import voluptuous as vol
import asyncio
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
        self._ir_remote_mac = None  # MAC _ir_remote (если хоть одну команду учили)
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
        # Подписываемся на изменения состояния
        self.hass.bus.async_listen(
            "state_changed",
            self._handle_power_state_change
        )
        # Получаем MAC и имя файла при инициализации
        hass.async_create_task(self._async_get_ir_remote_mac_and_commands())

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
            "ir_mac": self._ir_remote_mac,
            "ir_file": self._ir_remote_cmd_file
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
        # Путь к файлам команд Broadlink
        dir_path = Path(__file__).parent.parent.parent / ".storage"
        # Определяем шаблон
        filename_mask = f"broadlink_remote_{mac_address}_codes"
        # Ищем первый файл, который соответствует маске и является файлом
        for file_path in dir_path.iterdir():
            if file_path.is_file() and filename_mask in file_path.name:
                return file_path.absolute()
        return None  # Если файл не найден

    def _read_broadlink_commands(self, bfile):
        unique_id_key = self._unique_id
        if bfile and bfile.is_file():
            with bfile.open('r') as command_file:
                data = json.load(command_file)
                # Ищем запись по UID
                if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict):
                    if unique_id_key in data['data']:
                        # Переписываем найденные коды
                        return data['data'][unique_id_key].copy()
        return None

    def _get_ir_remote_mac_and_commands(self):
        # основа: https://github.com/mjg59/python-broadlink/issues/377
        # Листаем броадлинки и находим в файле 
        # с именем "broadlink_remote_XXXXXXXX_codes" (mac-адрес подставляем)
        # записи для устройства с self._unique_id
        devs = blk.discover(timeout=5)  # Все устройства Broadlink
        # Цикл по всем обнаруженным устройствам
        for d in devs:
            # Получаем строковое представление MAC-адреса в шестнадцатеричном формате
            mac_address = d.mac.hex()
            # Ищем файл команд
            ir_cmd_file = self._find_broadlink_file_by_mac(mac_address)
            # Читаем команды. Если файл- ок, будут команды, иначе - None
            self._learned_commands = self._read_broadlink_commands(ir_cmd_file)
            if self._learned_commands != None:
                self._ir_remote_cmd_file = ir_cmd_file
                self._ir_remote_mac = mac_address
                return  # Выход из цикла for, если данные найдены и считаны

    async def _async_get_ir_remote_mac_and_commands(self):
        # Используем add_executor_job для выполнения в фоновом потоке
        await self.hass.async_add_executor_job(self._get_ir_remote_mac_and_commands)

    def _get_learned_commands(self):
        """Короткая процедура обновления кодов из файла"""
        self._learned_commands = self._read_broadlink_commands(self._ir_remote_cmd_file)

    async def _async_get_learned_commands(self):
        """Асинхронный вызов короткой процедуры обновления кодов из файла"""
        # Используем add_executor_job для выполнения в фоновом потоке
        await self.hass.async_add_executor_job(self._get_learned_commands)

    async def async_check_command_existence(self, key_to_check):
        """Асинхронно проверяет наличие ключа в self._learned_commands."""
        if isinstance(self._learned_commands, dict):
            if key_to_check in self._learned_commands:
                return True
            else:
                return False
        else:
            return False

    async def async_update(self):
        """Fetch new state data for the media player."""
        # Возможно, вам все еще нужно периодическое обновление для других данных
        await self.hass.async_add_executor_job(self._get_learned_commands)

    async def _get_ir_status(self):
        """Get the IR status."""
        ir_state = self.hass.states.get(self._ir_remote)
        if ir_state and ir_state.state not in (None, "unknown", "unavailable"):
            return ir_state.state
        else:
            _LOGGER.warning("IR entity state is unavailable or unknown: %s", ir_state.state if ir_state else "None")
            return STATE_UNAVAILABLE

    @callback
    async def _handle_power_state_change(self, event):
        """Обработчик изменения состояния мощности."""
        if event.data.get("entity_id") == self._power_entity:
            new_state = event.data.get("new_state")
            if new_state and new_state.state not in (None, "unknown", "unavailable"):
                try:
                    power_value = float(new_state.state)
                    if power_value > POWER_THRESHOLD:
                        self._state = STATE_ON
                        self._attr_state = MediaPlayerState.ON
                    else:
                        self._state = STATE_OFF
                        self._attr_state = MediaPlayerState.OFF
                except ValueError:
                    _LOGGER.warning("Invalid power value: %s", new_state.state)
            else:
                _LOGGER.warning("Power entity state is unavailable or unknown: %s", new_state.state)
                self._state = STATE_OFF

            # Определяем доступность
            if new_state.state in (None, "unknown", "unavailable") or await self._get_ir_status() == STATE_UNAVAILABLE:
                self._is_unavailable = True
            else:
                self._is_unavailable = False

            self.async_write_ha_state()

# ===================================================================================

    async def handle_learn_command(self, call: ServiceCall):
        """Handle the service call to learn a command."""
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
