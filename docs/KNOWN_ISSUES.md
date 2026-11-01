# Known issues and validation limits

This describes the current experimental iPhone9,1 / D10AP iOS16.1 / 20B82 port.
It is not a device certification or a guarantee that every application works.
Use the device only for personal research, keep sensitive personal information
off it, and do not use it as a daily driver.

## Partial SEP support — do not configure a passcode

The device uses its collected stock SEP firmware with a ported iOS16 kernel and
compatibility changes. That is **partial SEP support**, not a full implementation
of the iOS16 passcode, authentication or data-protection stack.

Setting a device passcode has caused hangs and restarts. **Do not set one during
Setup Assistant or later in Settings.** In Setup Assistant choose **Passcode
Options → Don't Use Passcode**. Skip Touch ID setup if it requires a passcode.
Fingerprint enrollment has been observed, but it does not establish working
passcode unlock, third-party biometric authentication or other secure operations.

### VPN configuration approval

The system's VPN confirmation can appear and the user can select Allow, but
Settings then returns without saving the configuration. The observed chain is:

```text
nehelper → coreauthd → AppleCredentialManager → SEP
SEP command 36 returns acmErr=-3
ACMContextCreate returns -536870199 / 0xe00002c9
LocalAuthentication reports error -1000
Settings reports 0 VPN configurations
```

This is a local-authentication failure before tunnel startup. The exact SEP
command/protocol incompatibility has not been decoded. The error is in the same
subsystem as the passcode problems, but a common low-level cause has not been
proven. Research is currently deferred; no VPN-specific workaround is included.

Do not interpret this as evidence that replacing a VPN application's servers or
clearing all network preferences would repair the port.

## Camera preview, photos and video are different paths

- Front/rear camera operation and QR/barcode scanning have been observed in
  tested applications. Flashlight operation has also been observed.
- Still photos can be saved with **Settings → Camera → Formats → Most Compatible**.
- **Video recording is not working.** The AVE/video-encoding path is not operational.
  Camera preview or QR decoding working does not establish working video encoding.
- High Efficiency capture and panorama remain unresolved. Symptoms can include
  failed saves, invalid media or Camera app crashes.
- Loading an AVE image manually did not resolve the issue in prior testing.
  The normal full-iOS boot sequence deliberately omits AVE.

No claim is made about every capture format, resolution, frame rate or camera app.

## Microphone, Voice Memos, Siri and dictation

Microphone input and Voice Memos recording have been observed working. Siri and
keyboard dictation remain problematic. They use additional software and service
paths, so recording audio successfully does not imply that those features work.
Do not label the entire microphone path broken solely because Siri/dictation fails.

## Physical Home button and haptics

Vibration/haptics have been restored. The pressure-sensitive physical Home button
still does not function. Use **./run.sh assistive-touch** after booting full iOS
to enable the floating Home button over USB. Enabling it does not repair the
physical Home input path.

## Cellular/baseband — unresearched

The author has not investigated baseband support because the development
phone's cellular/SIM-related hardware is faulty and cannot provide meaningful
cellular test results. iPhone 7 has two baseband hardware variants. The author
has no GSM device and has not tested the GSM variant.

The installer currently accepts only iPhone9,1 / D10AP. Calls, SMS, cellular data,
baseband firmware compatibility and GSM support are not validated. No claim is
made that either baseband variant is fully supported or that both have the same
failure. This research is outside the current release scope.

## Standby, power and battery diagnostics

Battery percentage and charging information have been restored, but power
management is not qualified for daily use. Severe overnight battery depletion
has been observed while the display was off. An audio-related assertion that
prevented idle sleep was found in that investigation; a lasting fix was not
established. Display-off time alone is not proof of system sleep.

Some third-party battery tools may show incomplete fields. Missing diagnostic
fields alone are not proof that the fuel-gauge driver is absent. Battery aging,
charge behavior, accessory use, idle sleep and long-term thermal behavior need
additional testing. USB OTG and storage accessories are also unqualified.

## Apps and intentionally disabled services

Third-party App Store download, installation and launch have been observed
working. Some removable Apple apps carried over from iOS15 can crash. Delete the
affected app and download it again from the App Store before treating it as a
new port failure. This is not a guarantee that every Apple app or service works.

The current compatibility patch set retains disabled healthd and mobiletimerd
jobs from earlier thermal mitigation. Health, Sleep-related behavior, alarms
and timers must not be advertised as validated. Future changes should revisit
those choices rather than silently claiming full stock functionality.

## Scope of positive results

Display/GPU/UI, touch, USB device connectivity, SSH, Wi-Fi, Bluetooth, audio,
microphone, haptics, motion data, compass/location and battery readouts have
positive development-device observations. These are limited observations on
one supported configuration, not endurance testing or certification.

Do not assume stock iOS security or data protection. Kernel trust/enforcement
behavior is modified, SEP is partial, and this port is for personal research.
