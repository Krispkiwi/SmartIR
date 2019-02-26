import asyncio
import binascii
from distutils.version import StrictVersion
import json
import logging
import os.path
import requests
import struct
import voluptuous as vol

from homeassistant.const import (
    ATTR_FRIENDLY_NAME, __version__ as current_ha_version)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'smartir'
VERSION = '1.2.0'
VERSION_URL = (
    "https://raw.githubusercontent.com/smartHomeHub/SmartIR/master/version.json")
REMOTE_BASE_DIR = (
    "https://raw.githubusercontent.com/smartHomeHub/SmartIR/master/smartir/"
)
CONF_CHECK_UPDATES = 'check_updates'

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_CHECK_UPDATES, default=True): cv.boolean
    })
}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass, config):
    """Set up the SmartIR component."""
    conf = config.get(DOMAIN)

    async def check_updates(service):
        await _update(hass)

    async def update_component(service):
        await _update(hass, True)

    hass.services.async_register(DOMAIN, 'check_updates', check_updates)
    hass.services.async_register(DOMAIN, 'update_component', update_component)

    if conf[CONF_CHECK_UPDATES]:
        await _update(hass)

    return True

async def _update(hass, do_update = False):
    has_errors = False

    request = requests.get(VERSION_URL, stream=True, timeout=10)
    
    if request.status_code == 200:
        data = request.json()
        last_version = data['version']
        min_ha_version = data['minHAVersion']
        release_notes = data['releaseNotes']
        
        if StrictVersion(last_version) <= StrictVersion(VERSION):
            return
            
        if StrictVersion(current_ha_version) >= StrictVersion(min_ha_version):
            if do_update:
                files = data['files']
                abspath = os.path.dirname(os.path.abspath(__file__))

                for file in files:
                    try:
                        source = REMOTE_BASE_DIR + file
                        dest = os.path.join(abspath, file)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        Helper.downloader(source, dest)
                    except:
                        _LOGGER.error("Error updating %s. Please update the file manually.", file)
                        has_errors = True
            else:
                hass.components.persistent_notification.async_create(
                    release_notes, title='SmartIR')

        else:
            hass.components.persistent_notification.async_create(
                "There is a new version of SmartIR, but it is **incompatible** "
                "with your HA version. Please first update Home Assistant.", title='SmartIR')

    else:
        _LOGGER.error("Invalid response from the server while checking for a new version")
        has_errors = True

    if do_update:
        if has_errors:
            hass.components.persistent_notification.async_create(
                "There was an error updating SmartIR. Please "
                "check the logs for more information.", title='SmartIR')
        else:
            hass.components.persistent_notification.async_create(
                "Successfully updated to {}. Please restart Home Assistant."
                .format(last_version), title='SmartIR')

class Helper():
    @staticmethod
    def downloader(source, dest):
        req = requests.get(source, stream=True, timeout=10)

        if req.status_code == 200:
            with open(dest, 'wb') as fil:
                for chunk in req.iter_content(1024):
                    fil.write(chunk)
        else:
            raise Exception('File not found')

    @staticmethod
    def pronto2lirc(pronto):
        codes = [int(binascii.hexlify(pronto[i:i+2]), 16) for i in range(0, len(pronto), 2)]

        if codes[0]:
            raise ValueError('Pronto code should start with 0000')
        if len(codes) != 4 + 2 * (codes[2] + codes[3]):
            raise ValueError('Number of pulse widths does not match the preamble')

        frequency = 1 / (codes[1] * 0.241246)
        return [int(round(code / frequency)) for code in codes[4:]]

    @staticmethod
    def lirc2broadlink(pulses):
        array = bytearray()

        for pulse in pulses:
            pulse = int(pulse * 269 / 8192)

            if pulse < 256:
                array += bytearray(struct.pack('>B', pulse))
            else:
                array += bytearray([0x00])
                array += bytearray(struct.pack('>H', pulse))

        packet = bytearray([0x26, 0x00])
        packet += bytearray(struct.pack('<H', len(array)))
        packet += array
        packet += bytearray([0x0d, 0x05])

        # Add 0s to make ultimate packet size a multiple of 16 for 128-bit AES encryption.
        remainder = (len(packet) + 4) % 16
        if remainder:
            packet += bytearray(16 - remainder)

        return packet
