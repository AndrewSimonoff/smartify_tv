"""Константы для интеграции SmartifyTV."""
DOMAIN = "smartify_tv"
DEFAULT_NAME = "SmartifyTV"

CONF_POWER_ENTITY = "power_entity"
CONF_IR_REMOTE = "ir_remote"

# Пауза между нажатиями кнопок на иммитируемом пульте
INTERCOMMAND_PAUSE = 0.5

# Словарь основных команд пульта ТВ
COMMAND_NAMES = {
    "POWER_ON": "",
    "POWER_OFF": "",
    "VOLUME_UP": "",
    "VOLUME_DOWN": "",
    "MUTE": "",
    "UNMUTE": "",
    "CHANNEL_UP": "",
    "CHANNEL_DOWN": "",
    "SOURCE": "",
    "PLAY": "",
    "STOP": "",
    "PAUSE": "",
    "PLAYPAUSE": "",
    "KEY_0": "",
    "KEY_1": "",
    "KEY_2": "",
    "KEY_3": "",
    "KEY_4": "",
    "KEY_5": "",
    "KEY_6": "",
    "KEY_7": "",
    "KEY_8": "",
    "KEY_9": "",
    "UP": "",
    "DOWN": "",
    "LEFT": "",
    "RIGHT": "",
    "OK": "",
    "EXIT": "",
}
