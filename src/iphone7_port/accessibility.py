"""Host-only AssistiveTouch control through libimobiledevice / lockdown."""

import ctypes as C
from ctypes.util import find_library
import plistlib
from contextlib import contextmanager

from .console import say
from .core import PortError, require

DOMAIN = b'com.apple.Accessibility'
KEY = b'AssistiveTouchEnabledByiTunes'


def library(project, name):
    candidates = [str(project.root / 'Darwin/lib/lockdown' / (name + '.dylib')),
                  str(project.root / 'Darwin/lib' / (name + '.dylib'))]
    located = find_library(name.removeprefix('lib'))
    if located:
        candidates.append(located)
    for path in candidates:
        try:
            return C.CDLL(path)
        except OSError:
            pass
    raise PortError(f'Cannot load host library {name}. Restore the bundled Darwin/lib/lockdown directory for the supported Mac architecture.')


class Lockdown:
    def __init__(self, project):
        self.mobile = library(project, 'libimobiledevice-1.0')
        self.plist = library(project, 'libplist-2.0')
        ptr, string = C.c_void_p, C.c_char_p
        declarations = [
            (self.mobile, 'idevice_get_device_list', [C.POINTER(C.POINTER(string)), C.POINTER(C.c_int)], C.c_int),
            (self.mobile, 'idevice_device_list_free', [C.POINTER(string)], C.c_int),
            (self.mobile, 'idevice_new_with_options', [C.POINTER(ptr), string, C.c_int], C.c_int),
            (self.mobile, 'idevice_free', [ptr], C.c_int),
            (self.mobile, 'lockdownd_client_new_with_handshake', [ptr, C.POINTER(ptr), string], C.c_int),
            (self.mobile, 'lockdownd_client_free', [ptr], C.c_int),
            (self.mobile, 'lockdownd_get_value', [ptr, string, string, C.POINTER(ptr)], C.c_int),
            (self.mobile, 'lockdownd_set_value', [ptr, string, string, ptr], C.c_int),
            (self.mobile, 'lockdownd_strerror', [C.c_int], string),
            (self.plist, 'plist_new_uint', [C.c_uint64], ptr),
            (self.plist, 'plist_free', [ptr], None),
            (self.plist, 'plist_to_xml', [ptr, C.POINTER(ptr), C.POINTER(C.c_uint32)], None),
            (self.plist, 'plist_mem_free', [ptr], None),
        ]
        for owner, name, arguments, result in declarations:
            try:
                function = getattr(owner, name)
            except AttributeError as exc:
                raise PortError(f'Host library is missing required API {name}. Update libimobiledevice/libplist or replace the incompatible bundled libraries.') from exc
            function.argtypes, function.restype = arguments, result

    def check(self, code, operation):
        if code:
            message = self.mobile.lockdownd_strerror(code)
            text = message.decode(errors='replace') if message else str(code)
            raise PortError(f'{operation}: {text} ({code}). Unlock the phone and accept Trust if requested.')

    def devices(self):
        rows, count = C.POINTER(C.c_char_p)(), C.c_int()
        result = self.mobile.idevice_get_device_list(C.byref(rows), C.byref(count))
        require(result == 0, 'Cannot list USB devices through usbmuxd.')
        try:
            return [rows[i].decode() for i in range(count.value)]
        finally:
            if rows:
                self.mobile.idevice_device_list_free(rows)

    @contextmanager
    def connect(self, udid):
        device, client = C.c_void_p(), C.c_void_p()
        try:
            # IDEVICE_LOOKUP_USBMUX = 1 << 1; never select a network device.
            require(self.mobile.idevice_new_with_options(C.byref(device), udid.encode(), 2) == 0,
                    'Cannot open the selected USB device.')
            self.check(self.mobile.lockdownd_client_new_with_handshake(device, C.byref(client), b'iphone7-ios16'),
                       'Cannot connect to lockdown')
            yield client
        finally:
            if client:
                self.mobile.lockdownd_client_free(client)
            if device:
                self.mobile.idevice_free(device)

    def get(self, client, domain=None, key=None):
        node, xml, length = C.c_void_p(), C.c_void_p(), C.c_uint32()
        try:
            self.check(self.mobile.lockdownd_get_value(client, domain, key, C.byref(node)), 'Cannot read lockdown value')
            require(bool(node), 'Lockdown returned an empty value.')
            self.plist.plist_to_xml(node, C.byref(xml), C.byref(length))
            require(bool(xml) and 0 < length.value <= 4 * 1024 * 1024, 'Invalid lockdown property-list response.')
            return plistlib.loads(C.string_at(xml, length.value))
        finally:
            if xml:
                self.plist.plist_mem_free(xml)
            if node:
                self.plist.plist_free(node)

    def enable(self, client):
        # Apple's lockdown accessibility domain takes an integer, as used by
        # pymobiledevice3's set_assistive_touch implementation.
        node = self.plist.plist_new_uint(1)
        require(bool(node), 'Cannot allocate the AssistiveTouch setting.')
        # lockdownd_set_value transfers this node into its request dictionary
        # and frees it with that dictionary, including on transport errors.
        self.check(self.mobile.lockdownd_set_value(client, DOMAIN, KEY, node), 'Cannot enable AssistiveTouch')


def enable_assistive_touch(project, udid=None):
    identity = project.stage('device')['identity']
    api = Lockdown(project)
    devices = api.devices()
    require(bool(devices), 'No USB iPhone detected. Boot full iOS and connect its USB cable first.')
    if udid is None:
        require(len(devices) == 1, 'Multiple USB devices detected. Disconnect other devices or specify --udid.')
        udid = devices[0]
    require(udid in devices, 'The selected UDID is not connected through USB.')
    say('Enabling AssistiveTouch through USB lockdown.')
    with api.connect(udid) as client:
        info = api.get(client)
        require(isinstance(info, dict) and info.get('UniqueChipID') == int(identity['ECID'], 16)
                and info.get('ProductType') == project.profile['device']['product'],
                'The USB device does not match this project. No setting was changed.')
        require(info.get('ProductVersion') == project.profile['target']['version'] and
                info.get('BuildVersion') == project.profile['target']['build'],
                'Boot full iOS16.1 / 20B82 before enabling AssistiveTouch.')
        api.enable(client)
        require(api.get(client, DOMAIN, KEY) in (1, True), 'AssistiveTouch was requested but the enabled setting was not confirmed.')
    project.record('assistive-touch', {'enabled': True, 'transport': 'usb-lockdown'})
    say('AssistiveTouch enabled. The floating Home button should appear without rebooting.', 'success')
