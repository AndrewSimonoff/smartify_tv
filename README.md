## Описание

SmartifyTV — это интеграция, которая позволяет превратить ваш обычный телевизор в "умный", предоставляя возможность управления через Home Assistant (HASS) и голосовые ассистенты. С помощью SmartifyTV вы можете легко управлять вашим телевизором, используя голосовые команды или автоматизации в HASS.

## Возможности

- Управление каналами: Переключение каналов с помощью голосовых команд или автоматизаций.
- Регулировка громкости: Увеличение или уменьшение громкости телевизора.
- Включение/выключение: Управление питанием телевизора.
- Интеграция с HASS: Лёгкая настройка и управление через интерфейс и автоматизации Home Assistant.
- Поддержка голосовых ассистентов: Управление телевизором с помощью популярных голосовых ассистентов.

## Установка

1. Требования:
   - Установленный Home Assistant.
   - Любой обычный телевизор.
   - Розетка с функцией измерения мгновенной мощности (обязательно!).
   - IR-пульт (например, Broadlink).

2. Шаги установки:
   - Перейдите в интерфейс Home Assistant.
   - Откройте раздел "Интеграции" и выберите "SmartifyTV".
   - В процессе добавления выберите из списка реле, к которому подключен телевизор и IR-пульт, который будет отправлять команды.

3. Настройка:
   - Неодходимо обучить командам пульта.
   - В любой момент можно изменить розетку и пульт (например, в случае их замены).
   - В случае замены IR-пульта требуется переобучение командам.

4. Имена команд (встроенные) для обучения IR-пульта:
   - POWER_ON
   - POWER_OFF
   - VOLUME_UP
   - VOLUME_DOWN
   - MUTE
   - UNMUTE
   - CHANNEL_UP
   - CHANNEL_DOWN
   - KEY_0
   - KEY_1
   - KEY_2
   - KEY_3
   - KEY_4
   - KEY_5
   - KEY_6
   - KEY_7
   - KEY_8
   - KEY_9

## Примеры команд в формате YAML

1. Программирование команд (YAML):
   ВНИМАНИЕ!!! Обучение командам производится от имени устройства, созданного в рамках интеграции!
   
   action: smartifytv.learn_command
   data:
     command: POWER_ON


3. Переключение канала (YAML):
   
   action: media_player.play_media
   target:
     entity_id: media_player.smartifytv
   data:
     media_content_type: channel
     media_content_id: 17

##====================================================================##

## Description

SmartifyTV is an integration that allows you to turn your regular TV into a "smart" one, providing control through Home Assistant (HASS) and voice assistants. With SmartifyTV, you can easily manage your TV using voice commands or automations in HASS.

## Features

- Channel Control: Switch channels using voice commands or automations.
- Volume Adjustment: Increase or decrease the TV volume.
- Power On/Off: Control the TV's power.
- Integration with HASS: Easy setup and management through the Home Assistant interface and automations.
- Voice Assistant Support: Control the TV using popular voice assistants.

## Installation

1. Requirements:
   - Installed Home Assistant.
   - Any regular TV.
   - A power socket with instant power measurement capability (mandatory!).
   - An IR remote (e.g., Broadlink).

2. Installation Steps:
   - Go to the Home Assistant interface.
   - Open the "Integrations" section and select "SmartifyTV."
   - During the setup process, select the relay connected to the TV and the IR remote that will send commands.

3. Configuration:
   - You need to teach the remote commands.
   - You can change the socket and remote at any time (e.g., if they are replaced).
   - If the IR remote is replaced, retraining the commands is required.

4. Command Names (built-in) for IR Remote Training:
   - POWERON
   - POWEROFF
   - VOLUMEUP
   - VOLUMEDOWN
   - MUTE
   - UNMUTE
   - CHANNELUP
   - CHANNELDOWN
   - KEY0
   - KEY1
   - KEY2
   - KEY3
   - KEY4
   - KEY5
   - KEY6
   - KEY7
   - KEY8
   - KEY9

## Command Examples in YAML Format

1. Command Programming (YAML):
   ATTENTION!!! Command training is performed on behalf of the device created within the integration!

   action: smartifytv.learn_command
   data:
     command: POWER_ON

2. Channel Switching (YAML):

   action: media_player.play_media
   target:
     entity_id: media_player.smartifytv
   data:
     media_content_type: channel
     media_content_id: 17
