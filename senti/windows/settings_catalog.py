"""Static catalogue of Windows settings surfaces plus dynamic, ranked search.

This is the one deliberately hard-coded part of SENTI's Windows settings support: every
``ms-settings:`` URI (documented, hidden and legacy), Control Panel canonical names,
classic ``.cpl`` applets, ``.msc`` consoles, built-in management utilities, ``shell:`` known
folders and special ``shell:::{CLSID}`` namespaces. Runtime discovery
(``senti.windows.settings_discovery``) adds what is actually registered on the PC.

Only entries from this catalogue (or verified discovery) can be launched; free-form text
from the model is never passed to a launcher. Search is scored ranking, not a phrase table.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

MICROSOFT_SOURCE = (
    "https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings"
)
CONTROL_PANEL_SOURCE = (
    "https://learn.microsoft.com/en-us/windows/win32/shell/controlpanel-canonical-names"
)
CATALOGUE_VERSION = 2

# ms-settings rows: id, category, label, URI suffix, lifecycle, aliases, availability note,
# minimum build. Lifecycle: supported, conditional, deprecated, removed.
_ROWS = [
    # Accounts
    ("workplace", "Accounts", "Access work or school", "workplace", "supported", ("work account", "work or school", "organization account"), "", 0),
    ("email_accounts", "Accounts", "Email and app accounts", "emailandaccounts", "supported", ("email accounts", "mail accounts", "accounts"), "", 0),
    ("other_users", "Accounts", "Family and other users", "otherusers", "supported", ("other users", "family users", "user accounts"), "", 0),
    ("provisioning", "Accounts", "Provisioning", "provisioning", "conditional", ("provisioning package",), "Mobile/enterprise provisioning scenarios only.", 0),
    ("workplace_provisioning", "Accounts", "Workplace provisioning", "workplace-provisioning", "conditional", (), "Requires an enterprise provisioning package.", 0),
    ("workplace_repairtoken", "Accounts", "Workplace repair token", "workplace-repairtoken", "conditional", ("repair token",), "Enterprise/workplace account scenario.", 0),
    ("assigned_access", "Accounts", "Set up a kiosk", "assignedaccess", "supported", ("kiosk", "assigned access"), "", 0),
    ("signin_options", "Accounts", "Sign-in options", "signinoptions", "supported", ("login options", "password sign in", "windows hello"), "", 0),
    ("signin_dynamic_lock", "Accounts", "Dynamic lock sign-in options", "signinoptions-dynamiclock", "conditional", ("dynamic lock",), "Availability depends on Windows build and supported hardware.", 0),
    ("sync_settings", "Accounts", "Sync your settings", "sync", "supported", ("sync settings", "synchronization"), "", 0),
    ("backup_account", "Accounts", "Windows backup", "backup", "deprecated", ("backup", "account backup"), "Microsoft marks the legacy Backup URI as deprecated/redirected on Windows 11.", 0),
    ("windows_anywhere", "Accounts", "Windows Anywhere", "windowsanywhere", "conditional", (), "Only on Windows Anywhere-capable devices.", 0),
    ("face_enrollment", "Accounts", "Windows Hello face enrollment", "signinoptions-launchfaceenrollment", "conditional", ("face recognition setup", "face enrollment"), "Requires supported Windows Hello face hardware.", 0),
    ("fingerprint_enrollment", "Accounts", "Windows Hello fingerprint enrollment", "signinoptions-launchfingerprintenrollment", "conditional", ("fingerprint setup", "fingerprint enrollment"), "Requires a supported fingerprint reader.", 0),
    ("pin_enrollment", "Accounts", "Windows Hello PIN enrollment", "signinoptions-launchpinenrollment", "supported", ("pin setup", "hello pin"), "", 0),
    ("your_info", "Accounts", "Your info", "yourinfo", "supported", ("profile information", "account info"), "", 0),

    # Apps
    ("apps_features", "Apps", "Installed apps", "appsfeatures", "supported", ("apps", "installed applications", "programs", "apps and features", "apps features"), "", 0),
    ("app_features_detail", "Apps", "Per-app features and options", "appsfeatures-app", "conditional", ("app advanced options", "app features", "manage app permissions", "reset app"), "Microsoft documents an optional package-family-name parameter to target a specific app; SENTI only opens the base page and does not accept arbitrary URI parameters.", 0),
    ("apps_for_websites", "Apps", "Apps for websites", "appsforwebsites", "supported", ("website apps",), "", 0),
    ("default_apps", "Apps", "Default apps", "defaultapps", "conditional", ("default application", "file associations", "default browser"), "Per-application deep link parameters are supported only on qualifying Windows 11 builds; SENTI does not accept arbitrary query strings.", 22000),
    ("default_browser_settings", "Apps", "Default browser settings (legacy)", "defaultbrowsersettings", "deprecated", ("browser defaults legacy",), "Deprecated in Windows 11; use Default apps.", 0),
    ("optional_features", "Apps", "Optional features", "optionalfeatures", "supported", ("windows features", "optional windows features"), "", 0),
    ("offline_maps", "Apps", "Offline maps", "maps", "conditional", ("maps", "offline maps"), "Availability depends on Windows SKU/region.", 0),
    ("offline_maps_download", "Apps", "Download offline maps", "maps-downloadmaps", "conditional", ("download maps",), "Availability depends on Windows SKU/region.", 0),
    ("startup_apps", "Apps", "Startup apps", "startupapps", "supported", ("startup", "startup programs", "launch at sign in"), "", 0),
    ("video_playback", "Apps", "Video playback", "videoplayback", "supported", ("video settings",), "", 0),

    # Control Center
    ("control_center", "Control Center", "Control center", "controlcenter", "conditional", ("control center",), "Page availability varies by Windows version and device.", 0),

    # Devices
    ("autoplay", "Devices", "AutoPlay", "autoplay", "supported", ("autoplay", "removable media"), "", 0),
    ("bluetooth", "Devices", "Bluetooth", "bluetooth", "supported", ("bluetooth settings", "bluetooth devices"), "", 0),
    ("connected_devices", "Devices", "Connected devices", "connecteddevices", "supported", ("devices", "paired devices"), "", 0),
    ("camera", "Devices", "Camera settings", "camera", "conditional", ("camera", "camera settings"), "Windows 11 camera deep links can require a device-specific cameraId; plain URI opens the camera settings surface.", 22000),
    ("mouse_touchpad", "Devices", "Mouse and touchpad", "mousetouchpad", "conditional", ("mouse", "touchpad settings"), "Touchpad options appear only when compatible touchpad hardware is present.", 0),
    ("pen", "Devices", "Pen and Windows Ink", "pen", "conditional", ("windows ink", "stylus", "pen settings"), "Requires supported pen hardware for device-specific options.", 0),
    ("pen_button", "Devices", "Pen shortcut button", "pen-button", "conditional", ("pen button",), "Requires supported pen hardware.", 0),
    ("printers", "Devices", "Printers and scanners", "printers", "supported", ("printer", "scanner", "printing"), "", 0),
    ("touch", "Devices", "Touch", "devices-touch", "conditional", ("touch screen",), "Requires touch-capable hardware.", 0),
    ("touchpad", "Devices", "Touchpad", "devices-touchpad", "conditional", ("touchpad",), "Requires touchpad hardware.", 0),
    ("hardware_keyboard_suggestions", "Devices", "Text suggestions for hardware keyboard", "devicestyping-hwkbtextsuggestions", "supported", ("hardware keyboard suggestions", "text suggestions"), "", 0),
    ("typing", "Devices", "Typing", "typing", "supported", ("keyboard typing", "typing settings"), "", 0),
    ("usb", "Devices", "USB", "usb", "supported", ("usb settings", "usb devices"), "", 0),
    ("wheel", "Devices", "Wheel", "wheel", "conditional", ("surface dial",), "Only available when a Surface Dial device is paired.", 0),
    ("mobile_devices", "Devices", "Mobile devices", "mobile-devices", "supported", ("phone link", "your phone", "mobile phone"), "", 0),

    # Accessibility
    ("access_audio", "Accessibility", "Accessibility audio", "easeofaccess-audio", "supported", ("accessibility audio", "mono audio"), "", 0),
    ("closed_captions", "Accessibility", "Closed captions", "easeofaccess-closedcaptioning", "supported", ("captions", "subtitles"), "", 0),
    ("color_filters", "Accessibility", "Color filters", "easeofaccess-colorfilter", "supported", ("colour filters",), "", 0),
    ("adaptive_color_filter", "Accessibility", "Adaptive color filter settings", "easeofaccess-colorfilter-adaptivecolorlink", "conditional", ("adaptive color",), "Linked sub-page; availability varies by Windows build.", 0),
    ("blue_light_color_filter", "Accessibility", "Blue light color filter settings", "easeofaccess-colorfilter-bluelightlink", "conditional", ("blue light filter",), "Linked sub-page; availability varies by Windows build.", 0),
    ("access_display", "Accessibility", "Accessibility display", "easeofaccess-display", "supported", ("accessibility display", "visual accessibility"), "", 0),
    ("eye_control", "Accessibility", "Eye control", "easeofaccess-eyecontrol", "conditional", ("eye tracking", "eye control"), "Requires compatible eye-control hardware.", 0),
    ("hearing_devices", "Accessibility", "Hearing devices", "easeofaccess-hearingaids", "conditional", ("hearing aids",), "Added in Windows 11, version 24H2.", 26100),
    ("high_contrast", "Accessibility", "Contrast themes", "easeofaccess-highcontrast", "supported", ("high contrast", "contrast themes"), "", 0),
    ("access_keyboard", "Accessibility", "Accessibility keyboard", "easeofaccess-keyboard", "supported", ("on-screen keyboard", "sticky keys", "filter keys"), "", 0),
    ("magnifier", "Accessibility", "Magnifier", "easeofaccess-magnifier", "supported", ("screen magnifier",), "", 0),
    ("access_mouse", "Accessibility", "Accessibility mouse", "easeofaccess-mouse", "supported", ("mouse keys",), "", 0),
    ("mouse_pointer", "Accessibility", "Mouse pointer and touch", "easeofaccess-mousepointer", "supported", ("pointer size", "mouse pointer"), "", 0),
    ("narrator", "Accessibility", "Narrator", "easeofaccess-narrator", "supported", ("screen reader",), "", 0),
    ("narrator_autostart", "Accessibility", "Narrator startup", "easeofaccess-narrator-isautostartenabled", "conditional", ("narrator startup",), "Linked sub-page; availability varies by Windows build.", 0),
    ("speech_recognition", "Accessibility", "Accessibility speech", "easeofaccess-speechrecognition", "supported", ("speech recognition accessibility",), "", 0),
    ("text_cursor", "Accessibility", "Text cursor", "easeofaccess-cursor", "supported", ("cursor indicator",), "", 0),
    ("visual_effects", "Accessibility", "Visual effects", "easeofaccess-visualeffects", "supported", ("animation effects", "transparency effects"), "", 0),

    # Extras / family / gaming / mixed reality
    ("extras", "Extras", "Extras", "extras", "conditional", ("third party settings extras",), "Appears only when apps with extra settings pages are installed.", 0),
    ("family_group", "Family", "Family group", "family-group", "conditional", ("microsoft family", "family safety"), "Availability depends on account and family configuration.", 0),
    ("game_bar", "Gaming", "Xbox Game Bar", "gaming-gamebar", "supported", ("game bar", "xbox game bar"), "", 0),
    ("game_dvr", "Gaming", "Captures and Game DVR", "gaming-gamedvr", "supported", ("game capture", "game dvr", "recording games"), "", 0),
    ("game_mode", "Gaming", "Game Mode", "gaming-gamemode", "supported", ("gaming mode",), "", 0),
    ("xbox_mode", "Gaming", "Xbox fullscreen mode", "gaming-fullscreen", "conditional", ("xbox mode", "fullscreen gaming"), "Availability varies by Windows version and device.", 0),
    ("quiet_moments_game", "Gaming", "While playing a game", "quietmomentsgame", "conditional", ("do not disturb gaming", "focus while gaming"), "Legacy focus/quiet-moments page; availability varies by Windows version.", 0),
    ("trueplay", "Gaming", "TruePlay (removed)", "gaming-trueplay", "removed", ("trueplay",), "Microsoft states this feature was removed in Windows 10 version 1809.", 0),
    ("holographic_audio", "Gaming", "Mixed reality audio and speech", "holographic-audio", "conditional", ("mixed reality audio",), "Requires supported Windows Mixed Reality hardware/software.", 0),
    ("holographic_environment", "Gaming", "Mixed reality environment privacy", "privacy-holographic-environment", "conditional", ("mixed reality environment",), "Requires supported Windows Mixed Reality hardware/software.", 0),
    ("holographic_headset", "Gaming", "Mixed reality headset display", "holographic-headset", "conditional", ("headset display", "mixed reality headset"), "Requires supported Windows Mixed Reality hardware/software.", 0),
    ("holographic_management", "Gaming", "Mixed reality uninstall", "holographic-management", "conditional", ("mixed reality uninstall",), "Requires supported Windows Mixed Reality software.", 0),
    ("holographic_startup", "Gaming", "Mixed reality startup and desktop", "holographic-startupandesktop", "conditional", ("mixed reality startup",), "Requires supported Windows Mixed Reality hardware/software.", 0),

    # Network
    ("network_status", "Network and internet", "Network status", "network-status", "supported", ("network", "internet", "network and internet"), "", 0),
    ("network_advanced", "Network and internet", "Advanced network settings", "network-advancedsettings", "supported", ("advanced network settings", "network adapters"), "", 0),
    ("airplane_mode", "Network and internet", "Airplane mode", "network-airplanemode", "conditional", ("flight mode",), "Availability depends on radio hardware and OEM support.", 0),
    ("proximity", "Network and internet", "Proximity", "proximity", "conditional", ("nearby sharing proximity",), "Availability varies by Windows version and device.", 0),
    ("cellular", "Network and internet", "Cellular and SIM", "network-cellular", "conditional", ("sim settings", "mobile broadband"), "Requires supported cellular hardware/SIM.", 0),
    ("dial_up", "Network and internet", "Dial-up", "network-dialup", "supported", ("dial up connection",), "", 0),
    ("direct_access", "Network and internet", "DirectAccess", "network-directaccess", "conditional", ("direct access",), "Only available when DirectAccess is enabled.", 0),
    ("ethernet", "Network and internet", "Ethernet", "network-ethernet", "conditional", ("wired network", "lan"), "Requires an Ethernet interface.", 0),
    ("known_wifi_networks", "Network and internet", "Manage known Wi-Fi networks", "network-wifisettings", "conditional", ("known networks", "saved wifi", "saved wireless networks"), "Requires Wi-Fi support.", 0),
    ("mobile_hotspot", "Network and internet", "Mobile hotspot", "network-mobilehotspot", "conditional", ("hotspot", "mobile tethering"), "Availability depends on wireless adapter and policy.", 0),
    ("proxy", "Network and internet", "Proxy", "network-proxy", "supported", ("proxy settings",), "", 0),
    ("vpn", "Network and internet", "VPN", "network-vpn", "supported", ("virtual private network",), "", 0),
    ("wifi", "Network and internet", "Wi-Fi", "network-wifi", "conditional", ("wireless", "wireless network", "wifi settings"), "Only available when a Wi-Fi adapter is present.", 0),
    ("wifi_provisioning", "Network and internet", "Wi-Fi provisioning", "wifi-provisioning", "conditional", ("wireless provisioning",), "Availability depends on Windows version and provisioning support.", 0),

    # Personalization
    ("background", "Personalization", "Background", "personalization-background", "supported", ("wallpaper", "desktop background"), "", 0),
    ("start_places", "Personalization", "Folders on Start", "personalization-start-places", "supported", ("start folders",), "", 0),
    ("personalization_colors", "Personalization", "Personalization colors", "personalization-colors", "supported", ("accent color", "color mode", "colour settings"), "", 0),
    ("colors_legacy", "Personalization", "Colors (legacy shortcut)", "colors", "conditional", ("legacy colors",), "Legacy alias; use Personalization > Colors on current Windows 11.", 0),
    ("copilot_hardware_key", "Personalization", "Copilot key", "personalization-textinput-copilot-hardwarekey", "conditional", ("copilot keyboard key",), "Requires a supported keyboard/device.", 0),
    ("dynamic_lighting", "Personalization", "Dynamic Lighting", "personalization-lighting", "conditional", ("rgb lighting", "keyboard lighting",), "Requires supported Dynamic Lighting devices.", 0),
    ("fonts", "Personalization", "Fonts", "fonts", "supported", ("font settings",), "", 0),
    ("glance", "Personalization", "Glance (deprecated)", "personalization-glance", "deprecated", ("glance",), "Microsoft marks this URI deprecated.", 0),
    ("lock_screen", "Personalization", "Lock screen", "lockscreen", "supported", ("lock screen",), "", 0),
    ("navigation_bar", "Personalization", "Navigation bar (deprecated)", "personalization-navbar", "deprecated", ("navigation bar",), "Microsoft marks this URI deprecated.", 0),
    ("personalization", "Personalization", "Personalization home", "personalization", "supported", ("personalisation", "themes and appearance"), "", 0),
    ("start_personalization", "Personalization", "Start", "personalization-start", "supported", ("start menu", "start menu layout"), "", 0),
    ("taskbar", "Personalization", "Taskbar", "taskbar", "supported", ("task bar",), "", 0),
    ("text_input", "Personalization", "Text input", "personalization-textinput", "supported", ("text input",), "", 0),
    ("touch_keyboard", "Personalization", "Touch keyboard", "personalization-touchkeyboard", "conditional", ("on-screen touch keyboard",), "Touch keyboard options depend on device capabilities.", 0),
    ("themes", "Personalization", "Themes", "themes", "supported", ("theme settings",), "", 0),

    # Phone
    ("add_phone", "Phone", "Add a phone", "mobile-devices-addphone", "conditional", ("add phone", "link a phone"), "Requires the Phone Link experience.", 0),
    ("add_phone_direct", "Phone", "Open Phone Link", "mobile-devices-addphone-direct", "conditional", ("launch phone link",), "Opens the Phone Link app.", 0),
    ("device_usage", "Phone", "Device usage", "deviceusage", "supported", ("device usage",), "", 0),

    # Privacy
    ("privacy_accessory_apps", "Privacy", "Accessory apps (deprecated)", "privacy-accessoryapps", "deprecated", ("accessory apps",), "Microsoft marks this URI deprecated.", 0),
    ("privacy_account_info", "Privacy", "Account info privacy", "privacy-accountinfo", "supported", ("account information privacy",), "", 0),
    ("activity_history", "Privacy", "Activity history", "privacy-activityhistory", "supported", ("activity history privacy",), "", 0),
    ("advertising_id", "Privacy", "Advertising ID (deprecated)", "privacy-advertisingid", "deprecated", ("advertising identifier",), "Microsoft marks this URI deprecated.", 0),
    ("app_diagnostics", "Privacy", "App diagnostics", "privacy-appdiagnostics", "supported", ("diagnostic access",), "", 0),
    ("automatic_file_downloads", "Privacy", "Automatic file downloads", "privacy-automaticfiledownloads", "supported", ("automatic downloads",), "", 0),
    ("background_apps", "Privacy", "Background apps (deprecated)", "privacy-backgroundapps", "deprecated", ("background app permissions",), "Deprecated in Windows 11 21H2 and later; app-specific permissions are under Installed apps > Advanced options.", 0),
    ("background_spatial", "Privacy", "Background spatial perception", "privacy-backgroundspatialperception", "conditional", ("spatial perception privacy",), "Availability depends on device capabilities.", 0),
    ("privacy_calendar", "Privacy", "Calendar privacy", "privacy-calendar", "supported", ("calendar access",), "", 0),
    ("call_history", "Privacy", "Call history privacy", "privacy-callhistory", "supported", ("call history access",), "", 0),
    ("privacy_camera", "Privacy", "Camera privacy", "privacy-webcam", "supported", ("camera privacy", "webcam privacy"), "", 0),
    ("privacy_contacts", "Privacy", "Contacts privacy", "privacy-contacts", "supported", ("contacts access",), "", 0),
    ("privacy_documents", "Privacy", "Documents privacy", "privacy-documents", "supported", ("documents access",), "", 0),
    ("downloads_folder", "Privacy", "Downloads folder privacy", "privacy-downloadsfolder", "supported", ("downloads privacy",), "", 0),
    ("privacy_email", "Privacy", "Email privacy", "privacy-email", "supported", ("email access privacy",), "", 0),
    ("eye_tracker", "Privacy", "Eye tracker privacy", "privacy-eyetracker", "conditional", ("eye tracking privacy",), "Requires eye-tracker hardware.", 0),
    ("privacy_feedback", "Privacy", "Feedback and diagnostics privacy", "privacy-feedback", "supported", ("diagnostic data privacy",), "", 0),
    ("broad_file_system", "Privacy", "File system access privacy", "privacy-broadfilesystemaccess", "supported", ("filesystem privacy", "file system access"), "", 0),
    ("privacy", "Privacy", "Privacy home", "privacy", "supported", ("privacy settings",), "", 0),
    ("privacy_general", "Privacy", "General privacy", "privacy-general", "supported", ("general privacy settings",), "", 0),
    ("graphics_capture", "Privacy", "Graphics capture privacy", "privacy-graphicscaptureprogrammatic", "supported", ("screen capture privacy", "graphics capture"), "", 0),
    ("graphics_capture_borderless", "Privacy", "Borderless graphics capture privacy", "privacy-graphicscapturewithoutborder", "supported", ("borderless screen capture",), "", 0),
    ("speech_typing_privacy", "Privacy", "Inking and typing personalization", "privacy-speechtyping", "supported", ("inking and typing privacy",), "", 0),
    ("privacy_location", "Privacy", "Location privacy", "privacy-location", "supported", ("location access",), "", 0),
    ("privacy_messaging", "Privacy", "Messaging privacy", "privacy-messaging", "supported", ("sms privacy",), "", 0),
    ("privacy_microphone", "Privacy", "Microphone privacy", "privacy-microphone", "supported", ("microphone access",), "", 0),
    ("privacy_motion", "Privacy", "Motion privacy", "privacy-motion", "conditional", ("motion sensor privacy",), "Requires motion-capable hardware.", 0),
    ("music_library", "Privacy", "Music library privacy", "privacy-musiclibrary", "supported", ("music access",), "", 0),
    ("privacy_notifications", "Privacy", "Notifications privacy", "privacy-notifications", "supported", ("notification access privacy",), "", 0),
    ("privacy_other_devices", "Privacy", "Other devices privacy", "privacy-customdevices", "supported", ("custom devices",), "", 0),
    ("privacy_phone_calls", "Privacy", "Phone calls privacy", "privacy-phonecalls", "supported", ("phone call access",), "", 0),
    ("privacy_pictures", "Privacy", "Pictures library privacy", "privacy-pictures", "supported", ("picture access",), "", 0),
    ("privacy_radios", "Privacy", "Radios privacy", "privacy-radios", "supported", ("radio access privacy",), "", 0),
    ("privacy_speech", "Privacy", "Speech privacy", "privacy-speech", "supported", ("speech data privacy",), "", 0),
    ("privacy_tasks", "Privacy", "Tasks privacy", "privacy-tasks", "supported", ("task access privacy",), "", 0),
    ("privacy_videos", "Privacy", "Videos library privacy", "privacy-videos", "supported", ("video access",), "", 0),
    ("voice_activation", "Privacy", "Voice activation privacy", "privacy-voiceactivation", "supported", ("voice activation",), "", 0),

    # Search
    ("search", "Search", "Search", "search", "supported", ("windows search",), "", 0),
    ("search_details", "Search", "Search more details", "search-moredetails", "supported", ("search details",), "", 0),
    ("search_permissions", "Search", "Search permissions", "search-permissions", "supported", ("search permission",), "", 0),

    # Sound
    ("volume_mixer", "Sound", "Volume mixer", "apps-volume", "supported", ("app volume", "per-app volume"), "", 0),
    ("sound", "Sound", "Sound", "sound", "supported", ("audio settings",), "", 0),
    ("sound_devices", "Sound", "Sound devices", "sound-devices", "supported", ("audio devices", "input output devices"), "", 0),
    ("default_microphone", "Sound", "Default microphone properties", "sound-defaultinputproperties", "supported", ("input device", "default input"), "", 0),
    ("default_audio_output", "Sound", "Default audio output properties", "sound-defaultoutputproperties", "supported", ("output device", "default output"), "", 0),
    ("sound_device_properties", "Sound", "Specific sound device properties (parameter required)", "sound-properties", "conditional", ("sound endpoint properties", "audio endpoint properties"), "Requires a device endpointId or interfaceId. SENTI intentionally does not accept raw URI query strings for this page.", 0),

    # System
    ("about", "System", "About this PC", "about", "supported", ("system information", "device specifications", "pc specs"), "", 0),
    ("display_advanced", "System", "Advanced display", "display-advanced", "supported", ("advanced display", "refresh rate", "monitor information"), "On Windows 11 this URI opens Display; Advanced display is a subsection, not a separate page.", 0),
    ("battery_saver", "System", "Battery saver", "batterysaver", "conditional", ("battery saver",), "Only on devices with a battery.", 0),
    ("battery_saver_settings", "System", "Battery saver settings", "batterysaver-settings", "conditional", ("battery saver options",), "Only on devices with a battery.", 0),
    ("battery_usage", "System", "Battery usage", "batterysaver-usagedetails", "conditional", ("battery usage details",), "Only on devices with a battery.", 0),
    ("clipboard", "System", "Clipboard", "clipboard", "supported", ("clipboard settings", "clipboard history"), "", 0),
    ("save_locations", "System", "Default save locations", "savelocations", "supported", ("default save locations",), "", 0),
    ("display", "System", "Display", "display", "supported", ("screen settings", "monitor settings", "resolution"), "", 0),
    ("screen_rotation", "System", "Screen rotation", "screenrotation", "conditional", ("rotate screen", "rotation lock"), "Depends on sensor/orientation-capable hardware.", 0),
    ("duplicate_display", "System", "Project or duplicate displays", "quietmomentspresentation", "supported", ("project screen", "duplicate display", "second screen"), "", 0),
    ("focus_scheduled", "System", "Focus during scheduled hours", "quietmomentsscheduled", "conditional", ("scheduled focus",), "Legacy quiet-moments URI; availability varies by Windows version.", 0),
    ("device_encryption", "System", "Device encryption", "deviceencryption", "conditional", ("bitlocker", "device encryption"), "Availability depends on Windows edition, hardware and policy.", 0),
    ("energy_recommendations", "System", "Energy recommendations", "energyrecommendations", "conditional", ("energy settings",), "Microsoft documents availability from Windows 11 22H2 build 22624/February Moment update.", 22624),
    ("focus_assist", "System", "Focus assist (legacy)", "quiethours", "deprecated", ("quiet hours", "focus assist"), "Legacy URI; use Notifications and Do not disturb on current Windows 11.", 0),
    ("graphics_settings", "System", "Graphics settings", "display-advancedgraphics", "conditional", ("graphics settings", "gpu app preference"), "Only on devices that support advanced graphics options.", 0),
    ("graphics_default_settings", "System", "Default graphics settings", "display-advancedgraphics-default", "conditional", ("graphics default settings",), "Only on devices that support advanced graphics options.", 0),
    ("multitasking", "System", "Multitasking", "multitasking", "supported", ("snap windows", "snap layouts", "virtual desktops settings"), "", 0),
    ("multitasking_sgupdate", "System", "Multitasking (subpage)", "multitasking-sgupdate", "conditional", ("snap settings subpage",), "Linked sub-page; availability varies by Windows build.", 0),
    ("night_light", "System", "Night light", "nightlight", "supported", ("nightlight", "blue light",), "", 0),
    ("projecting", "System", "Projecting to this PC", "project", "supported", ("wireless display receiver",), "", 0),
    ("cross_device", "System", "Cross-device experiences", "crossdevice", "conditional", ("shared experiences", "cross device"), "Availability depends on Windows version and linked-device services.", 0),
    ("tablet_mode", "System", "Tablet mode (removed)", "tabletmode", "removed", ("tablet mode",), "Microsoft states this Settings page was removed in Windows 11.", 22000),
    ("notifications", "System", "Notifications", "notifications", "supported", ("notification settings", "do not disturb"), "", 0),
    ("remote_desktop", "System", "Remote Desktop", "remotedesktop", "conditional", ("rdp", "remote desktop settings"), "Availability depends on Windows edition and policy.", 0),
    ("phone_legacy", "System", "Phone (deprecated)", "phone", "deprecated", ("phone settings legacy",), "Microsoft marks this URI deprecated.", 0),
    ("power", "System", "Power and sleep", "powersleep", "supported", ("power settings", "sleep settings"), "", 0),
    ("presence_sensing", "System", "Presence sensing", "presence", "conditional", ("presence sensor",), "Added in a Windows 11 22H2 Moment update; requires supported sensor hardware.", 22624),
    ("storage_sense", "System", "Storage Sense", "storagesense", "supported", ("storage settings", "free space"), "", 0),
    ("storage_policies", "System", "Storage policies", "storagepolicies", "supported", ("storage sense policy",), "", 0),
    ("storage_recommendations", "System", "Storage recommendations", "storagerecommendations", "supported", ("cleanup recommendations",), "", 0),
    ("disks_volumes", "System", "Disks and volumes", "disksandvolumes", "supported", ("disk partitions", "volumes settings"), "", 0),

    # Time and language
    ("date_time", "Time and language", "Date and time", "dateandtime", "supported", ("clock", "time zone", "date settings"), "", 0),
    ("japanese_ime", "Time and language", "Japanese IME settings", "regionlanguage-jpnime", "conditional", ("japanese input method",), "Available when Microsoft Japanese IME is installed.", 0),
    ("region_formatting", "Time and language", "Region and format", "regionformatting", "supported", ("regional format", "country format"), "", 0),
    ("keyboard_language", "Time and language", "Language and keyboard", "keyboard", "supported", ("language settings", "keyboard language"), "", 0),
    ("keyboard_advanced", "Time and language", "Advanced keyboard settings", "keyboard-advanced", "supported", ("advanced keyboard", "input method"), "", 0),
    ("region_language", "Time and language", "Language and region", "regionlanguage", "supported", ("language and region", "display language"), "", 0),
    ("bopomofo_ime", "Time and language", "Bopomofo IME settings", "regionlanguage-bpmfime", "conditional", ("bopomofo input method",), "Requires the corresponding input method.", 0),
    ("cangjie_ime", "Time and language", "Cangjie IME settings", "regionlanguage-cangjieime", "conditional", ("cangjie input method",), "Requires the corresponding input method.", 0),
    ("wubi_udp", "Time and language", "Wubi UDP IME settings", "regionlanguage-chsime-wubi-udp", "conditional", ("wubi udp",), "Requires the corresponding input method.", 0),
    ("quick_ime", "Time and language", "Quick IME settings", "regionlanguage-quickime", "conditional", ("quick input method",), "Requires the corresponding input method.", 0),
    ("korean_ime", "Time and language", "Korean IME settings", "regionlanguage-korime", "conditional", ("korean input method",), "Requires the corresponding input method.", 0),
    ("pinyin_ime", "Time and language", "Pinyin IME settings", "regionlanguage-chsime-pinyin", "conditional", ("microsoft pinyin",), "Available when Microsoft Pinyin IME is installed.", 0),
    ("pinyin_domain_lexicon", "Time and language", "Pinyin domain lexicon", "regionlanguage-chsime-pinyin-domainlexicon", "conditional", ("pinyin lexicon",), "Requires Microsoft Pinyin IME.", 0),
    ("pinyin_key_config", "Time and language", "Pinyin key configuration", "regionlanguage-chsime-pinyin-keyconfig", "conditional", ("pinyin keyboard config",), "Requires Microsoft Pinyin IME.", 0),
    ("pinyin_udp", "Time and language", "Pinyin UDP settings", "regionlanguage-chsime-pinyin-udp", "conditional", ("pinyin udp",), "Requires Microsoft Pinyin IME.", 0),
    ("speech", "Time and language", "Speech", "speech", "supported", ("speech language",), "", 0),
    ("wubi_ime", "Time and language", "Wubi IME settings", "regionlanguage-chsime-wubi", "conditional", ("microsoft wubi",), "Available when Microsoft Wubi IME is installed.", 0),

    # Update and security
    ("activation", "Update and security", "Windows activation", "activation", "supported", ("activate windows", "product activation"), "", 0),
    ("backup_legacy", "Update and security", "Backup (legacy redirect)", "backup", "deprecated", ("windows backup legacy",), "Microsoft says this page was removed in Windows 11 and opens Sync.", 22000),
    ("delivery_optimization", "Update and security", "Delivery Optimization", "delivery-optimization", "supported", ("update delivery optimization",), "", 0),
    ("delivery_activity", "Update and security", "Delivery Optimization activity", "delivery-optimization-activity", "supported", ("delivery optimization statistics",), "", 0),
    ("delivery_advanced", "Update and security", "Delivery Optimization advanced options", "delivery-optimization-advanced", "supported", ("delivery optimization advanced",), "", 0),
    ("find_my_device", "Update and security", "Find my device", "findmydevice", "conditional", ("find device",), "Requires a supported account/device configuration.", 0),
    ("developers", "Update and security", "For developers", "developers", "supported", ("developer settings", "developer mode"), "", 0),
    ("recovery", "Update and security", "Recovery", "recovery", "supported", ("reset this pc", "advanced startup", "recovery options"), "", 0),
    ("security_key_enrollment", "Update and security", "Security key enrollment", "signinoptions-launchsecuritykeyenrollment", "conditional", ("fido security key", "security key setup"), "Requires a supported security key and account.", 0),
    ("troubleshoot", "Update and security", "Troubleshoot", "troubleshoot", "supported", ("troubleshooting", "troubleshooters"), "", 0),
    ("windows_security", "Update and security", "Windows Security", "windowsdefender", "supported", ("defender", "windows defender", "security center"), "", 0),
    ("windows_insider", "Update and security", "Windows Insider Program", "windowsinsider", "conditional", ("insider program",), "Only present when the user is enrolled in Windows Insider Program.", 0),
    ("windows_insider_optin", "Update and security", "Windows Insider opt-in", "windowsinsider-optin", "conditional", ("insider opt in",), "Availability depends on Insider enrollment and Windows build.", 0),
    ("windows_update", "Update and security", "Windows Update", "windowsupdate", "supported", ("update", "check updates", "windows updates"), "", 0),
    ("windows_update_action", "Update and security", "Windows Update action", "windowsupdate-action", "supported", ("update action",), "", 0),
    ("update_active_hours", "Update and security", "Windows Update active hours", "windowsupdate-activehours", "supported", ("active hours",), "", 0),
    ("update_options", "Update and security", "Windows Update advanced options", "windowsupdate-options", "supported", ("update advanced options",), "", 0),
    ("optional_updates", "Update and security", "Optional updates", "windowsupdate-optionalupdates", "supported", ("driver updates", "optional driver updates"), "", 0),
    ("update_restart_options", "Update and security", "Windows Update restart options", "windowsupdate-restartoptions", "supported", ("restart options",), "", 0),
    ("update_seeker", "Update and security", "Windows Update seeker on demand", "windowsupdate-seekerondemand", "conditional", ("seeker on demand",), "Specialized Windows Update entry point; availability varies by build.", 0),
    ("update_history", "Update and security", "Windows Update history", "windowsupdate-history", "supported", ("update history", "installed updates"), "", 0),
]


# Additional ms-settings URIs (documented in the Microsoft list or observed on current builds).
_ROWS += [
    ("settings_home", "System", "Settings app", "", "supported", ("settings app", "all settings", "settings kholo"), "Opens the Settings app at its default page.", 0),
    ("settings_home_page", "System", "Settings Home (recommended settings)", "home", "conditional", ("settings home page", "recommended settings"), "Windows 11 23H2 and later. Observed on current builds; not in the main Microsoft list.", 22631),
    ("saved_passkeys", "Accounts", "Passkeys", "savedpasskeys", "conditional", ("passkeys", "saved passkeys", "manage passkeys"), "Windows 11 23H2 and later. Observed on current builds; not in the main Microsoft list.", 22631),
    ("data_usage", "Network and internet", "Data usage", "datausage", "supported", ("data usage", "network usage", "data limit", "kitna data"), "", 0),
    ("nfc", "Network and internet", "NFC", "nfctransactions", "conditional", ("nfc", "tap to pay", "nfc transactions"), "Requires NFC hardware.", 0),
    ("gaming_broadcasting", "Gaming", "Broadcasting (legacy)", "gaming-broadcasting", "deprecated", ("broadcast", "game streaming"), "Windows 10 only; retired together with Mixer.", 0),
    ("xbox_networking", "Gaming", "Xbox Networking", "gaming-xboxnetworking", "conditional", ("xbox network", "nat type", "xbox live connection"), "Windows 10 page; may redirect on Windows 11.", 0),
    ("ease_other_options", "Accessibility", "Other accessibility options (legacy)", "easeofaccess-otheroptions", "deprecated", ("other accessibility options",), "Windows 10 page; Microsoft marks it deprecated.", 0),
    ("cortana", "Search", "Cortana (legacy)", "cortana", "deprecated", ("cortana",), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("cortana_language", "Search", "Cortana language (legacy)", "cortana-language", "deprecated", ("cortana language",), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("cortana_more_details", "Search", "Cortana more details (legacy)", "cortana-moredetails", "deprecated", ("cortana details",), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("cortana_notifications", "Search", "Cortana across devices (legacy)", "cortana-notifications", "deprecated", ("cortana notifications",), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("cortana_permissions", "Search", "Cortana permissions and history (legacy)", "cortana-permissions", "deprecated", ("cortana permissions",), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("cortana_talk", "Search", "Talk to Cortana (legacy)", "cortana-talktocortana", "deprecated", ("talk to cortana", "hey cortana"), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("cortana_windows_search", "Search", "Cortana Windows search (legacy)", "cortana-windowssearch", "deprecated", ("cortana search",), "Windows 10 Cortana settings; Cortana has been retired.", 0),
    ("surfacehub_accounts", "Surface Hub", "Surface Hub accounts", "surfacehub-accounts", "conditional", ("surface hub accounts",), "Surface Hub devices only.", 0),
    ("surfacehub_calling", "Surface Hub", "Surface Hub team conferencing", "surfacehub-calling", "conditional", ("surface hub calling",), "Surface Hub devices only.", 0),
    ("surfacehub_device_management", "Surface Hub", "Surface Hub team device management", "surfacehub-devicemanagenent", "conditional", ("surface hub device management",), "Surface Hub devices only. The URI spelling 'devicemanagenent' is Microsoft's own.", 0),
    ("surfacehub_session_cleanup", "Surface Hub", "Surface Hub session cleanup", "surfacehub-sessioncleanup", "conditional", ("surface hub session cleanup",), "Surface Hub devices only.", 0),
    ("surfacehub_welcome", "Surface Hub", "Surface Hub welcome screen", "surfacehub-welcome", "conditional", ("surface hub welcome",), "Surface Hub devices only.", 0),
    ("quiet_moments_home", "System", "Focus while at home (legacy)", "quietmomentshome", "deprecated", ("focus at home",), "Legacy Focus assist automatic rule; availability varies by build.", 0),
    ("display_language_add", "Time and language", "Add a display language", "regionlanguage-adddisplaylanguage", "supported", ("add language", "install language", "nayi bhasha"), "", 0),
    ("language_options", "Time and language", "Language options", "regionlanguage-languageoptions", "supported", ("language pack options", "language features"), "", 0),
    ("display_language_set", "Time and language", "Set display language", "regionlanguage-setdisplaylanguage", "supported", ("change display language", "bhasha badlo", "windows language"), "", 0),
]

_HINGLISH = {
    "sound": ("awaaz", "aawaz", "volume"),
    "volume_mixer": ("awaaz", "app ki awaaz"),
    "display": ("chamak", "brightness", "screen"),
    "night_light": ("aankh", "raat ki light", "eye protection"),
    "date_time": ("samay", "time", "tareekh", "ghadi"),
    "region_language": ("bhasha",),
    "background": ("wallpaper badlo", "wallpaper"),
    "wifi": ("net", "wifi chalu", "internet"),
    "bluetooth": ("bluetooth chalu", "bt", "earbuds", "headphones connect"),
    "apps_features": ("uninstall apps", "app hatao", "remove apps", "delete app"),
    "power": ("battery", "sleep", "screen timeout"),
    "battery_saver": ("battery bachao",),
    "signin_options": ("password badlo", "change password", "pin badlo"),
    "windows_update": ("update karo", "naya update"),
    "storage_sense": ("jagah", "disk space", "storage full"),
    "network_advanced": ("dns", "dns settings", "ip address", "adapter settings", "network adapter"),
    "ethernet": ("dns", "ip settings"),
    "mouse_touchpad": ("mouse speed",),
    "printers": ("printer add karo",),
}

# id, category, title, canonical name, CLSID, /page argument, aliases, availability, lifecycle
_CONTROL_NAME_ROWS = [
    ("cp_security_maintenance", "Security and Maintenance", "Microsoft.ActionCenter", "{BB64F8A7-BEE7-4E1A-AB8D-7D8273F7FDB6}", None, ("action center", "maintenance", "security center", "reliability"), "", "supported"),
    ("cp_administrative_tools", "Windows Tools (Administrative Tools)", "Microsoft.AdministrativeTools", "{D20EA4E1-3957-11d2-A40B-0C5020524153}", None, ("administrative tools", "admin tools", "windows tools"), "", "supported"),
    ("cp_autoplay", "AutoPlay (Control Panel)", "Microsoft.AutoPlay", "{9C60DE1E-E5FC-40f4-A487-460851A8D915}", None, ("autoplay defaults", "cd autoplay"), "", "supported"),
    ("cp_backup_restore", "Backup and Restore (Windows 7)", "Microsoft.BackupAndRestore", "{B98A2BEA-7D42-4558-8BD1-832F41BAC6FD}", None, ("system image", "backup and restore", "windows 7 backup"), "", "supported"),
    ("cp_biometric_devices", "Biometric Devices", "Microsoft.BiometricDevices", "{0142e4d0-fb7a-11dc-ba4a-000ffe7ab428}", None, ("fingerprint reader", "biometrics"), "Present only with biometric hardware/drivers.", "conditional"),
    ("cp_bitlocker", "BitLocker Drive Encryption", "Microsoft.BitLockerDriveEncryption", "{D9EF8727-CAC2-4e60-809E-86F80A666C91}", None, ("bitlocker", "drive encryption", "recovery key"), "Full management on Pro/Enterprise/Education; Home uses Device encryption.", "conditional"),
    ("cp_color_management", "Color Management", "Microsoft.ColorManagement", "{B2C761C6-29BC-4f19-9251-E6195265BAF1}", None, ("icc profile", "color profile", "monitor profile"), "", "supported"),
    ("cp_credential_manager", "Credential Manager", "Microsoft.CredentialManager", "{1206F5F1-0569-412C-8FEC-3204630DFB70}", None, ("saved passwords", "windows credentials", "stored passwords", "web credentials"), "", "supported"),
    ("cp_date_time", "Date and Time (Control Panel)", "Microsoft.DateAndTime", "{E2E7934B-DCE5-43C4-9576-7FE4F75E7480}", None, ("internet time", "additional clocks", "time zone classic"), "", "supported"),
    ("cp_default_programs", "Default Programs", "Microsoft.DefaultPrograms", "{17cd9488-1228-4b2f-88ce-4298e93e0966}", None, ("file type associations", "set default programs"), "Mostly redirects to Settings > Default apps on Windows 11.", "supported"),
    ("cp_device_manager", "Device Manager (Control Panel)", "Microsoft.DeviceManager", "{74246bfc-4c96-11d0-abef-0020af6b0b7a}", None, ("device manager", "drivers", "hardware devices"), "", "supported"),
    ("cp_devices_printers", "Devices and Printers", "Microsoft.DevicesAndPrinters", "{A8A91A66-3A7D-4424-8D24-04E180695C7A}", None, ("devices and printers", "printer list", "device center"), "May redirect to Settings > Bluetooth & devices on recent Windows 11 builds.", "supported"),
    ("cp_ease_of_access", "Ease of Access Center", "Microsoft.EaseOfAccessCenter", "{D555645E-D4F8-4c29-A827-D93C859C4F2A}", None, ("ease of access", "accessibility control panel"), "", "supported"),
    ("cp_folder_options", "File Explorer Options", "Microsoft.FolderOptions", "{6DFD7C5C-2451-11d3-A299-00C04F8EF6AF}", None, ("folder options", "show hidden files", "file extensions", "hidden files dikhao"), "", "supported"),
    ("cp_file_history", "File History", "Microsoft.FileHistory", "{F6B6E965-E9B2-444B-9286-10C9152EDBC5}", None, ("file history", "file backup"), "", "supported"),
    ("cp_fonts", "Fonts folder", "Microsoft.Fonts", "{BD84B380-8CA2-1069-AB1D-08000948F534}", None, ("fonts folder", "installed fonts"), "", "supported"),
    ("cp_game_controllers", "Game Controllers", "Microsoft.GameControllers", "{259EF4B1-E6C9-4176-B574-481532C9BCE8}", None, ("joystick", "gamepad", "controller calibration"), "", "supported"),
    ("cp_get_programs", "Get Programs (from network)", "Microsoft.GetPrograms", "{15eae92e-f17a-4431-9f28-805e482dafd4}", None, ("install program from network",), "Domain-published applications only.", "conditional"),
    ("cp_homegroup", "HomeGroup (removed)", "Microsoft.HomeGroup", "{67CA7650-96E6-4FDD-BB43-A8E774F73A57}", None, ("homegroup",), "Removed in Windows 10 version 1803.", "removed"),
    ("cp_indexing_options", "Indexing Options", "Microsoft.IndexingOptions", "{87D66A43-7B11-4A28-9811-C86EE395ACF7}", None, ("search index", "indexing", "rebuild index"), "", "supported"),
    ("cp_infrared", "Infrared", "Microsoft.Infrared", "{A0275511-0E86-4ECA-97C2-ECD8F1221D08}", None, ("irda", "infrared"), "Requires infrared hardware.", "conditional"),
    ("cp_internet_options", "Internet Options", "Microsoft.InternetOptions", "{A3DD4F92-658A-410F-84FD-6FBBBEF2FFFE}", None, ("internet properties", "ie options", "lan settings"), "", "supported"),
    ("cp_iscsi_initiator", "iSCSI Initiator (Control Panel)", "Microsoft.iSCSIInitiator", "{A304259D-52B8-4526-8B1A-A1D6CECC8243}", None, ("iscsi",), "", "supported"),
    ("cp_keyboard", "Keyboard Properties", "Microsoft.Keyboard", "{725BE8F7-668E-4C7B-8F90-46BDB0936430}", None, ("keyboard repeat rate", "cursor blink rate"), "", "supported"),
    ("cp_language", "Language (removed)", "Microsoft.Language", "{BF782CC9-5A52-4A17-806C-2A894FFEEAC5}", None, ("language control panel",), "Removed in Windows 10 version 1803; use Settings > Time & language.", "removed"),
    ("cp_mouse", "Mouse Properties", "Microsoft.Mouse", "{6C8EEC18-8D75-41B2-A177-8831D59D2D50}", None, ("mouse properties", "pointer scheme", "double click speed"), "", "supported"),
    ("cp_network_sharing", "Network and Sharing Center", "Microsoft.NetworkAndSharingCenter", "{8E908FC9-BECC-40f6-915B-F4CA0E70D03D}", None, ("network and sharing center", "network sharing", "set up new connection"), "", "supported"),
    ("cp_advanced_sharing", "Advanced sharing settings", "Microsoft.NetworkAndSharingCenter", None, "Advanced", ("network discovery", "file and printer sharing", "advanced sharing", "public folder sharing"), "On Windows 11 22H2+ this may open the Settings equivalent.", "supported"),
    ("cp_notification_area_icons", "Notification Area Icons (legacy)", "Microsoft.NotificationAreaIcons", "{05d7b0f4-2121-4eff-bf6b-ed3f69b894d9}", None, ("tray icons", "system tray icons"), "Redirects to Taskbar settings on current Windows.", "deprecated"),
    ("cp_pen_touch", "Pen and Touch", "Microsoft.PenAndTouch", "{F82DF8F7-8B9F-442E-A48C-818EA735FF9B}", None, ("pen and touch", "touch feedback"), "Requires pen or touch hardware.", "conditional"),
    ("cp_personalization", "Personalization (Control Panel)", "Microsoft.Personalization", "{ED834ED6-4B5A-4bfe-8F11-A626DCB6A921}", None, ("classic personalization",), "Redirects to Settings > Personalization on current Windows.", "supported"),
    ("cp_phone_modem", "Phone and Modem", "Microsoft.PhoneAndModem", "{40419485-C444-4567-851A-2DD7BFA1684D}", None, ("modem", "dialing rules"), "", "supported"),
    ("cp_power_options", "Power Options", "Microsoft.PowerOptions", "{025A5937-A6BE-4686-A844-36FE4BEC8B6D}", None, ("power plan", "power options", "high performance"), "", "supported"),
    ("cp_power_buttons", "Choose what the power buttons do", "Microsoft.PowerOptions", None, "pageGlobalSettings", ("power button", "lid close action", "fast startup", "laptop lid"), "", "supported"),
    ("cp_create_power_plan", "Create a power plan", "Microsoft.PowerOptions", None, "pageCreateNewPlan", ("new power plan", "custom power plan"), "", "supported"),
    ("cp_programs_features", "Programs and Features", "Microsoft.ProgramsAndFeatures", "{7b81be6a-ce2b-4676-a29e-eb907a5126c5}", None, ("uninstall a program", "uninstall programs", "add remove programs", "program hatao", "repair program"), "", "supported"),
    ("cp_recovery", "Recovery (Control Panel)", "Microsoft.Recovery", "{9FE63AFD-59CF-4419-9775-ABCC3849F861}", None, ("system restore", "recovery drive", "configure system restore"), "", "supported"),
    ("cp_region", "Region (Control Panel)", "Microsoft.RegionAndLanguage", "{62D8ED13-C9D0-4CE8-A914-47DD628FB1B0}", None, ("regional settings", "system locale", "unicode language", "date format"), "", "supported"),
    ("cp_remoteapp", "RemoteApp and Desktop Connections", "Microsoft.RemoteAppAndDesktopConnections", "{241D7C96-F8BF-4F85-B01F-E2B043341A4B}", None, ("remoteapp", "workspace connections"), "", "supported"),
    ("cp_scanners_cameras", "Scanners and Cameras", "Microsoft.ScannersAndCameras", None, None, ("scanner", "wia devices"), "May be missing on some builds.", "conditional"),
    ("cp_sound", "Sound (Control Panel)", "Microsoft.Sound", "{F2DDFC82-8F12-4CDD-B7DC-D4FE1425AA4D}", None, ("playback devices", "recording devices", "sound scheme", "classic sound"), "", "supported"),
    ("cp_speech_recognition", "Speech Recognition", "Microsoft.SpeechRecognition", "{58E3C745-D971-4081-9034-86E34B30836A}", None, ("windows speech recognition", "train voice"), "Windows Speech Recognition is deprecated in favour of Voice access.", "supported"),
    ("cp_storage_spaces", "Storage Spaces", "Microsoft.StorageSpaces", "{F942C606-0914-47AB-BE56-1321B8035096}", None, ("storage pool", "storage spaces"), "", "supported"),
    ("cp_sync_center", "Sync Center", "Microsoft.SyncCenter", "{9C73F5E5-7AE7-4E32-A8E8-8D23B85255BF}", None, ("offline files", "sync center"), "", "supported"),
    ("cp_system", "System (Control Panel)", "Microsoft.System", "{BB06C0E4-D293-4f75-8A90-CB05B6477EEE}", None, ("system properties", "computer properties"), "Redirects to Settings > About on current Windows.", "supported"),
    ("cp_tablet_pc", "Tablet PC Settings", "Microsoft.TabletPCSettings", "{80F3F1D5-FECA-45F3-BC32-752C152E456E}", None, ("tablet pc", "calibrate screen", "handedness"), "Requires pen or touch hardware.", "conditional"),
    ("cp_taskbar", "Taskbar and Navigation", "Microsoft.Taskbar", "{0DF44EAA-FF21-4412-828E-260A8728E7F1}", None, ("taskbar properties",), "Redirects to Settings > Taskbar on current Windows.", "supported"),
    ("cp_text_to_speech", "Text to Speech", "Microsoft.TextToSpeech", "{D17D1D6D-CC3F-4815-8FE3-607E7D5D10B3}", None, ("speech properties", "tts voice", "sapi voice"), "", "supported"),
    ("cp_troubleshooting", "Troubleshooting (Control Panel)", "Microsoft.Troubleshooting", "{C58C4893-3BE0-4B45-ABB5-A63E4B8C8651}", None, ("classic troubleshooters",), "", "supported"),
    ("cp_user_accounts", "User Accounts (Control Panel)", "Microsoft.UserAccounts", "{60632754-c523-4b62-b45c-4172da012619}", None, ("user accounts", "change account type", "uac"), "", "supported"),
    ("cp_windows_defender", "Windows Defender (legacy)", "Microsoft.WindowsDefender", None, None, ("defender control panel",), "Opens Windows Security on current Windows.", "deprecated"),
    ("cp_windows_firewall", "Windows Defender Firewall", "Microsoft.WindowsFirewall", "{4026492F-2F69-46B8-B9BF-5654FC07E423}", None, ("firewall", "allow app through firewall"), "", "supported"),
    ("cp_mobility_center", "Windows Mobility Center", "Microsoft.MobilityCenter", "{5ea4f148-308c-46d7-98a9-49041b1dd468}", None, ("mobility center", "presentation settings"), "Laptops and tablets.", "conditional"),
    ("cp_work_folders", "Work Folders", "Microsoft.WorkFolders", "{ECDB0924-4208-451E-8EE0-373C0956DE16}", None, ("work folders",), "Requires an organisation Work Folders server.", "supported"),
    ("cp_display", "Display (legacy)", "Microsoft.Display", "{C555438B-3C23-4769-A71F-B6D3D9B6053A}", None, ("display control panel",), "Redirects to Settings > Display.", "deprecated"),
    ("cp_windows_update", "Windows Update (Control Panel, removed)", "Microsoft.WindowsUpdate", "{36eef7db-88ad-4e81-ad49-0e313f0c35f8}", None, ("classic windows update",), "Removed in Windows 10; use Settings > Windows Update.", "removed"),
    ("cp_parental_controls", "Parental Controls (removed)", "Microsoft.ParentalControls", "{96AE8D84-A250-4520-95A5-A47A7E3C548B}", None, ("parental controls",), "Removed in Windows 10; use Microsoft Family Safety.", "removed"),
    ("cp_performance_info", "Performance Information and Tools (removed)", "Microsoft.PerformanceInformationAndTools", "{78F3955E-3B90-4184-BD14-5397C15F1EFC}", None, ("windows experience index",), "Removed in Windows 8.1.", "removed"),
]

# id, category, title, cpl file, argument suffix (tab), aliases, availability, lifecycle
_CPL_ROWS = [
    ("cpl_appwiz", "Programs and Features (appwiz.cpl)", "appwiz.cpl", "", ("uninstall a program", "uninstall programs", "add remove programs", "installed programs"), ""),
    ("cpl_bthprops", "Bluetooth devices (bthprops.cpl)", "bthprops.cpl", "", ("bluetooth classic",), "Redirects to Settings > Bluetooth & devices on current Windows."),
    ("cpl_desk", "Display (desk.cpl)", "desk.cpl", "", ("screen resolution classic",), "Redirects to Settings > Display on current Windows."),
    ("cpl_firewall", "Windows Defender Firewall (firewall.cpl)", "firewall.cpl", "", ("firewall", "firewall on off"), ""),
    ("cpl_hdwwiz", "Device Manager (hdwwiz.cpl)", "hdwwiz.cpl", "", ("device manager", "hardware"), "hdwwiz.cpl opens Device Manager; the Add Hardware wizard is hdwwiz.exe."),
    ("cpl_inetcpl", "Internet Properties", "inetcpl.cpl", "", ("internet options", "internet properties"), ""),
    ("cpl_inetcpl_general", "Internet Properties: General", "inetcpl.cpl", ",,0", ("browsing history", "home page ie"), ""),
    ("cpl_inetcpl_security", "Internet Properties: Security", "inetcpl.cpl", ",,1", ("internet security zones", "trusted sites"), ""),
    ("cpl_inetcpl_privacy", "Internet Properties: Privacy", "inetcpl.cpl", ",,2", ("pop up blocker", "cookies ie"), ""),
    ("cpl_inetcpl_content", "Internet Properties: Content", "inetcpl.cpl", ",,3", ("certificates internet", "autocomplete"), ""),
    ("cpl_inetcpl_connections", "Internet Properties: Connections", "inetcpl.cpl", ",,4", ("lan settings", "proxy classic", "dial up connections"), ""),
    ("cpl_inetcpl_programs", "Internet Properties: Programs", "inetcpl.cpl", ",,5", ("manage add ons", "html editor"), ""),
    ("cpl_inetcpl_advanced", "Internet Properties: Advanced", "inetcpl.cpl", ",,6", ("tls settings", "reset internet explorer", "ssl settings"), ""),
    ("cpl_intl", "Region (intl.cpl)", "intl.cpl", "", ("regional format classic", "system locale", "date format"), ""),
    ("cpl_irprops", "Infrared (irprops.cpl)", "irprops.cpl", "", ("infrared",), "Requires infrared hardware."),
    ("cpl_joy", "Game Controllers (joy.cpl)", "joy.cpl", "", ("joystick", "gamepad test", "controller"), ""),
    ("cpl_main", "Mouse Properties (main.cpl)", "main.cpl", "", ("mouse properties", "pointer speed", "double click"), ""),
    ("cpl_mmsys", "Sound (mmsys.cpl)", "mmsys.cpl", "", ("sound control panel", "classic sound"), ""),
    ("cpl_mmsys_playback", "Sound: Playback devices", "mmsys.cpl", ",,0", ("playback devices", "speakers", "default speaker"), ""),
    ("cpl_mmsys_recording", "Sound: Recording devices", "mmsys.cpl", ",,1", ("recording devices", "microphone level", "mic boost"), ""),
    ("cpl_mmsys_sounds", "Sound: Sounds (sound scheme)", "mmsys.cpl", ",,2", ("sound scheme", "system sounds", "startup sound"), ""),
    ("cpl_mmsys_communications", "Sound: Communications", "mmsys.cpl", ",,3", ("communications activity", "reduce volume calls"), ""),
    ("cpl_ncpa", "Network Connections (ncpa.cpl)", "ncpa.cpl", "", ("network connections", "adapter settings", "change adapter options", "dns", "ip address", "ipv4", "network adapters"), ""),
    ("cpl_powercfg", "Power Options (powercfg.cpl)", "powercfg.cpl", "", ("power plan", "power options"), ""),
    ("cpl_sysdm", "System Properties", "sysdm.cpl", "", ("system properties", "computer name"), ""),
    ("cpl_sysdm_computer_name", "System Properties: Computer Name", "sysdm.cpl", ",,1", ("computer name", "workgroup", "join domain", "rename pc"), ""),
    ("cpl_sysdm_hardware", "System Properties: Hardware", "sysdm.cpl", ",,2", ("device installation settings", "driver download settings"), ""),
    ("cpl_sysdm_advanced", "System Properties: Advanced", "sysdm.cpl", ",,3", ("environment variables", "performance options", "virtual memory", "startup and recovery"), ""),
    ("cpl_sysdm_protection", "System Properties: System Protection", "sysdm.cpl", ",,4", ("system protection", "restore point", "create restore point"), ""),
    ("cpl_sysdm_remote", "System Properties: Remote", "sysdm.cpl", ",,5", ("remote assistance", "remote desktop classic"), ""),
    ("cpl_tabletpc", "Tablet PC Settings (tabletpc.cpl)", "tabletpc.cpl", "", ("pen calibration", "tablet pc"), "Requires pen or touch hardware."),
    ("cpl_telephon", "Phone and Modem (telephon.cpl)", "telephon.cpl", "", ("modem", "dialing rules"), ""),
    ("cpl_timedate", "Date and Time (timedate.cpl)", "timedate.cpl", "", ("internet time", "time sync classic"), ""),
    ("cpl_wscui", "Security and Maintenance (wscui.cpl)", "wscui.cpl", "", ("security and maintenance", "action center"), ""),
]

# id, category, title, msc file, aliases, availability, risk
_MSC_ROWS = [
    ("msc_azman", "Authorization Manager", "azman.msc", ("authorization manager",), "", "controlled"),
    ("msc_certlm", "Certificates (Local Computer)", "certlm.msc", ("machine certificates", "computer certificates"), "Requires administrator rights to change.", "controlled"),
    ("msc_certmgr", "Certificates (Current User)", "certmgr.msc", ("certificate manager", "user certificates", "certificates"), "", "controlled"),
    ("msc_comexp", "Component Services", "comexp.msc", ("component services", "dcom config", "dcomcnfg"), "", "controlled"),
    ("msc_compmgmt", "Computer Management", "compmgmt.msc", ("computer management",), "", "controlled"),
    ("msc_devmgmt", "Device Manager", "devmgmt.msc", ("device manager", "drivers", "driver update", "hardware devices"), "", "low"),
    ("msc_diskmgmt", "Disk Management", "diskmgmt.msc", ("disk management", "partitions", "format drive", "drive letter"), "", "controlled"),
    ("msc_eventvwr", "Event Viewer", "eventvwr.msc", ("event viewer", "event logs", "error logs", "crash logs"), "", "low"),
    ("msc_fsmgmt", "Shared Folders", "fsmgmt.msc", ("shared folders", "open files", "network shares"), "", "controlled"),
    ("msc_gpedit", "Local Group Policy Editor", "gpedit.msc", ("group policy", "gpedit", "local policy"), "Pro/Enterprise/Education only.", "controlled"),
    ("msc_lusrmgr", "Local Users and Groups", "lusrmgr.msc", ("local users", "local groups", "user groups"), "Fully functional on Pro/Enterprise/Education; limited on Home.", "controlled"),
    ("msc_perfmon", "Performance Monitor", "perfmon.msc", ("performance monitor", "perfmon", "performance counters"), "", "low"),
    ("msc_printmanagement", "Print Management", "printmanagement.msc", ("print management", "print server"), "Pro/Enterprise; may require the Print Management optional feature.", "controlled"),
    ("msc_rsop", "Resultant Set of Policy", "rsop.msc", ("rsop", "applied policies"), "Pro/Enterprise/Education only; deprecated in favour of gpresult.", "low"),
    ("msc_secpol", "Local Security Policy", "secpol.msc", ("security policy", "secpol", "password policy", "user rights"), "Pro/Enterprise/Education only.", "controlled"),
    ("msc_services", "Services", "services.msc", ("services", "windows services", "service manager"), "", "controlled"),
    ("msc_taskschd", "Task Scheduler", "taskschd.msc", ("task scheduler", "scheduled tasks"), "", "controlled"),
    ("msc_tpm", "TPM Management", "tpm.msc", ("tpm", "trusted platform module", "security chip"), "", "controlled"),
    ("msc_wf", "Windows Defender Firewall with Advanced Security", "wf.msc", ("advanced firewall", "firewall rules", "inbound rules", "outbound rules"), "", "controlled"),
    ("msc_wmimgmt", "WMI Control", "wmimgmt.msc", ("wmi control", "wmi"), "", "controlled"),
    ("msc_devmoderunas", "Developer Mode Run-As-User configuration", "DevModeRunAsUserConfig.msc", ("developer mode run as",), "Present on builds with developer-mode features.", "controlled"),
    ("msc_virtmgmt", "Hyper-V Manager", "virtmgmt.msc", ("hyper v", "virtual machines", "hyper-v manager"), "Pro/Enterprise/Education with the Hyper-V feature enabled.", "controlled"),
    ("msc_gpmc", "Group Policy Management", "gpmc.msc", ("group policy management", "gpo"), "Requires RSAT: Group Policy Management Tools.", "controlled"),
    ("msc_dsa", "Active Directory Users and Computers", "dsa.msc", ("active directory users", "aduc"), "Requires RSAT: Active Directory tools.", "controlled"),
    ("msc_dssite", "Active Directory Sites and Services", "dssite.msc", ("ad sites",), "Requires RSAT: Active Directory tools.", "controlled"),
    ("msc_domain", "Active Directory Domains and Trusts", "domain.msc", ("domain trusts",), "Requires RSAT: Active Directory tools.", "controlled"),
    ("msc_adsiedit", "ADSI Edit", "adsiedit.msc", ("adsi edit",), "Requires RSAT: Active Directory tools.", "controlled"),
    ("msc_dnsmgmt", "DNS Manager", "dnsmgmt.msc", ("dns server manager",), "Requires RSAT: DNS Server tools.", "controlled"),
    ("msc_dhcpmgmt", "DHCP Manager", "dhcpmgmt.msc", ("dhcp server",), "Requires RSAT: DHCP Server tools.", "controlled"),
]

# id, category, title, executable, fixed arguments, aliases, availability, risk
_UTILITY_ROWS = [
    ("util_msconfig", "System Configuration (msconfig)", "msconfig.exe", None, ("msconfig", "system configuration", "boot options", "safe mode", "selective startup"), "", "controlled"),
    ("util_msinfo32", "System Information (msinfo32)", "msinfo32.exe", None, ("system information", "msinfo", "pc specs", "bios version", "hardware details"), "", "low"),
    ("util_resmon", "Resource Monitor", "resmon.exe", None, ("resource monitor", "resmon", "what is using disk", "network activity"), "", "low"),
    ("util_regedit", "Registry Editor", "regedit.exe", None, ("registry", "regedit", "registry editor"), "Lives in %SystemRoot%; edits can break Windows.", "controlled"),
    ("util_dxdiag", "DirectX Diagnostic Tool", "dxdiag.exe", None, ("dxdiag", "directx", "graphics driver info", "gpu info"), "", "low"),
    ("util_mdsched", "Windows Memory Diagnostic", "mdsched.exe", None, ("memory diagnostic", "ram test", "memory test"), "Offers to restart the PC; nothing runs until the user chooses.", "low"),
    ("util_cleanmgr", "Disk Cleanup", "cleanmgr.exe", None, ("disk cleanup", "cleanmgr", "temp files delete", "free up space"), "", "low"),
    ("util_dfrgui", "Defragment and Optimize Drives", "dfrgui.exe", None, ("defrag", "optimize drives", "trim ssd"), "", "low"),
    ("util_optionalfeatures", "Windows Features (turn features on or off)", "optionalfeatures.exe", None, ("windows features", "turn windows features on or off", "hyper v enable", "wsl enable", "telnet client"), "", "low"),
    ("util_sysprops_advanced", "System Properties: Advanced (SystemPropertiesAdvanced)", "SystemPropertiesAdvanced.exe", None, ("advanced system settings", "environment variables", "performance options", "startup and recovery"), "", "low"),
    ("util_sysprops_performance", "Performance Options", "SystemPropertiesPerformance.exe", None, ("performance options", "visual effects classic", "virtual memory", "paging file", "best performance"), "", "low"),
    ("util_sysprops_protection", "System Protection (restore points)", "SystemPropertiesProtection.exe", None, ("system protection", "create restore point", "restore point"), "", "low"),
    ("util_sysprops_remote", "Remote settings (System Properties)", "SystemPropertiesRemote.exe", None, ("remote assistance settings", "allow remote connections"), "", "low"),
    ("util_sysprops_computer_name", "Computer name (System Properties)", "SystemPropertiesComputerName.exe", None, ("computer name", "rename computer", "workgroup", "domain join"), "", "low"),
    ("util_sysprops_hardware", "Hardware (System Properties)", "SystemPropertiesHardware.exe", None, ("device installation settings",), "", "low"),
    ("util_sysprops_dep", "Data Execution Prevention", "SystemPropertiesDataExecutionPrevention.exe", None, ("dep", "data execution prevention"), "", "low"),
    ("util_environment_variables", "Environment Variables", "rundll32.exe", "sysdm.cpl,EditEnvironmentVariables", ("environment variables", "env vars", "path variable", "edit path", "user variables"), "Opens the per-user Environment Variables dialog.", "low"),
    ("util_stored_credentials", "Stored User Names and Passwords", "rundll32.exe", "keymgr.dll,KRShowKeyMgr", ("stored user names", "key manager", "saved network passwords"), "", "low"),
    ("util_print_server", "Print Server Properties", "rundll32.exe", "printui.dll,PrintUIEntry /s", ("print server properties", "printer drivers", "printer ports"), "", "low"),
    ("util_rstrui", "System Restore", "rstrui.exe", None, ("system restore", "restore pc", "rollback windows"), "Wizard only; nothing is restored until the user confirms.", "low"),
    ("util_userpasswords2", "User Accounts (advanced: control userpasswords2)", "control.exe", "userpasswords2", ("userpasswords2", "auto login", "automatic sign in", "advanced user accounts"), "", "controlled"),
    ("util_netplwiz", "User Accounts (netplwiz)", "netplwiz.exe", None, ("netplwiz", "auto login", "users must enter password"), "", "controlled"),
    ("util_sigverif", "File Signature Verification", "sigverif.exe", None, ("signature verification", "unsigned drivers"), "", "low"),
    ("util_verifier", "Driver Verifier Manager", "verifier.exe", None, ("driver verifier", "verifier"), "Misconfiguration can cause boot failures.", "controlled"),
    ("util_eudcedit", "Private Character Editor", "eudcedit.exe", None, ("private character editor", "eudc"), "", "low"),
    ("util_charmap", "Character Map", "charmap.exe", None, ("character map", "special characters", "symbols"), "", "low"),
    ("util_colorcpl", "Color Management (colorcpl)", "colorcpl.exe", None, ("color profiles", "icc"), "", "low"),
    ("util_cttune", "ClearType Text Tuner", "cttune.exe", None, ("cleartype", "text sharpness", "blurry text"), "", "low"),
    ("util_dccw", "Display Color Calibration", "dccw.exe", None, ("calibrate display", "color calibration", "gamma"), "", "low"),
    ("util_iscsicpl", "iSCSI Initiator", "iscsicpl.exe", None, ("iscsi initiator",), "", "low"),
    ("util_odbcad32", "ODBC Data Sources (64-bit)", "odbcad32.exe", None, ("odbc", "data sources", "dsn"), "", "low"),
    ("util_recoverydrive", "Recovery Drive creator", "recoverydrive.exe", None, ("recovery drive", "recovery usb"), "Wizard only; the USB drive is erased only after confirmation.", "low"),
    ("util_fsquirt", "Bluetooth File Transfer", "fsquirt.exe", None, ("bluetooth file transfer", "send file bluetooth", "receive file bluetooth"), "Requires Bluetooth hardware.", "low"),
    ("util_wfs", "Windows Fax and Scan", "WFS.exe", None, ("fax", "scan document", "windows fax and scan"), "Optional feature; not installed by default on all editions.", "low"),
    ("util_perfmon_reliability", "Reliability Monitor", "perfmon.exe", "/rel", ("reliability monitor", "reliability history", "crash history"), "", "low"),
    ("util_taskmgr", "Task Manager", "taskmgr.exe", None, ("task manager", "end task", "startup apps classic"), "", "low"),
    ("util_winver", "About Windows (winver)", "winver.exe", None, ("winver", "windows version", "build number"), "", "low"),
    ("util_mstsc", "Remote Desktop Connection", "mstsc.exe", None, ("remote desktop connection", "rdp client", "mstsc"), "", "low"),
    ("util_msra", "Windows Remote Assistance", "msra.exe", None, ("remote assistance",), "", "low"),
    ("util_uac_settings", "User Account Control settings", "UserAccountControlSettings.exe", None, ("uac", "user account control"), "", "controlled"),
    ("util_tabcal", "Digitizer Calibration Tool", "tabcal.exe", None, ("touch calibration", "pen calibration"), "Requires pen or touch hardware.", "low"),
    ("util_credwiz", "Back up stored credentials", "credwiz.exe", None, ("backup credentials", "restore credentials"), "", "low"),
    ("util_rekeywiz", "Encrypting File System (EFS) certificates", "rekeywiz.exe", None, ("efs", "file encryption certificate"), "EFS is not available on Home editions.", "low"),
    ("util_sdclt", "Backup and Restore (sdclt)", "sdclt.exe", None, ("backup and restore", "system image backup"), "", "low"),
    ("util_mblctr", "Windows Mobility Center (mblctr)", "mblctr.exe", None, ("mobility center",), "Laptops and tablets.", "low"),
    ("util_rasphone", "Remote Access Phonebook", "rasphone.exe", None, ("dial up phonebook", "vpn phonebook"), "", "low"),
    ("util_sndvol", "Volume Mixer (classic)", "sndvol.exe", None, ("classic volume mixer", "sndvol"), "", "low"),
    ("util_osk", "On-Screen Keyboard", "osk.exe", None, ("on screen keyboard", "virtual keyboard"), "", "low"),
    ("util_magnify", "Magnifier", "magnify.exe", None, ("magnifier", "zoom screen"), "", "low"),
    ("util_narrator", "Narrator", "narrator.exe", None, ("narrator", "screen reader"), "", "low"),
    ("util_slui", "Windows Activation (slui)", "slui.exe", None, ("activation", "product key", "slui"), "", "low"),
    ("util_shrpubw", "Create a Shared Folder wizard", "shrpubw.exe", None, ("create share", "share folder wizard"), "", "controlled"),
    ("util_lpksetup", "Install or uninstall display languages", "lpksetup.exe", None, ("language pack setup", "lpksetup"), "", "controlled"),
    ("util_mrt", "Malicious Software Removal Tool", "mrt.exe", None, ("mrt", "malicious software removal"), "Present after Windows Update installs it.", "low"),
    ("util_psr", "Steps Recorder", "psr.exe", None, ("steps recorder", "problem steps recorder"), "Deprecated; removed in recent Windows 11 builds.", "low"),
    ("util_hdwwiz", "Add Hardware wizard", "hdwwiz.exe", None, ("add hardware", "legacy hardware"), "", "low"),
    ("util_device_pairing", "Add a device (pairing wizard)", "DevicePairingWizard.exe", None, ("add a device", "pair device"), "", "low"),
    ("util_printui", "Printer settings (printui)", "printui.exe", None, ("printui",), "", "low"),
    ("util_dcomcnfg", "Component Services (dcomcnfg)", "dcomcnfg.exe", None, ("dcomcnfg", "dcom"), "", "controlled"),
    ("util_mobsync", "Sync Center (mobsync)", "mobsync.exe", None, ("mobsync", "offline files sync"), "", "low"),
    ("util_wiaacmgr", "Scanner and Camera wizard", "wiaacmgr.exe", None, ("scan wizard", "import from scanner"), "Requires a WIA scanner or camera.", "low"),
    ("util_filehistory", "File History (FileHistory.exe)", "FileHistory.exe", None, ("restore files file history",), "", "low"),
    ("util_tpminit", "TPM initialization wizard", "TpmInit.exe", None, ("tpm init", "prepare tpm"), "", "controlled"),
    ("util_computer_defaults", "Set program access and computer defaults", "ComputerDefaults.exe", None, ("program access", "computer defaults"), "", "low"),
    ("util_dialer", "Phone Dialer", "dialer.exe", None, ("phone dialer",), "", "low"),
    ("util_dpiscaling", "Display scaling (dpiscaling)", "dpiscaling.exe", None, ("dpi scaling", "scaling"), "Redirects to Settings > Display.", "low"),
    ("util_cliconfg", "SQL Server Client Network Utility", "cliconfg.exe", None, ("sql client config",), "", "low"),
    ("util_ease_dialog", "Accessibility shortcuts dialog", "EaseOfAccessDialog.exe", None, ("ease of access dialog",), "", "low"),
    ("util_explorer", "File Explorer", "explorer.exe", None, ("file explorer", "explorer", "my files"), "Lives in %SystemRoot%.", "low"),
]

# id, title, known-folder canonical name, aliases
_SHELL_FOLDER_ROWS = [
    ("shell_downloads", "Downloads folder", "Downloads", ("downloads", "downloaded files")),
    ("shell_desktop", "Desktop folder", "Desktop", ("desktop folder",)),
    ("shell_documents", "Documents folder", "Personal", ("documents", "my documents")),
    ("shell_pictures", "Pictures folder", "My Pictures", ("pictures", "photos folder")),
    ("shell_music", "Music folder", "My Music", ("music",)),
    ("shell_videos", "Videos folder", "My Video", ("videos",)),
    ("shell_appdata", "AppData Roaming folder", "AppData", ("appdata", "roaming"),),
    ("shell_local_appdata", "AppData Local folder", "Local AppData", ("local appdata",)),
    ("shell_local_appdata_low", "AppData LocalLow folder", "LocalAppDataLow", ("locallow",)),
    ("shell_startup", "Startup folder (current user)", "Startup", ("startup folder", "run at login folder")),
    ("shell_common_startup", "Startup folder (all users)", "Common Startup", ("all users startup",)),
    ("shell_start_menu", "Start Menu folder", "Start Menu", ("start menu folder",)),
    ("shell_common_start_menu", "Start Menu folder (all users)", "Common Start Menu", ("all users start menu",)),
    ("shell_programs", "Start Menu Programs folder", "Programs", ("start menu programs",)),
    ("shell_common_programs", "Start Menu Programs (all users)", "Common Programs", ("all users programs",)),
    ("shell_sendto", "Send To folder", "SendTo", ("send to menu",)),
    ("shell_recent", "Recent items folder", "Recent", ("recent files",)),
    ("shell_fonts", "Fonts folder (shell)", "Fonts", ("fonts folder",)),
    ("shell_windows", "Windows folder", "Windows", ("windows directory",)),
    ("shell_system", "System32 folder", "System", ("system32",)),
    ("shell_systemx86", "SysWOW64 folder", "SystemX86", ("syswow64",)),
    ("shell_program_files", "Program Files folder", "ProgramFiles", ("program files",)),
    ("shell_program_files_x86", "Program Files (x86) folder", "ProgramFilesX86", ("program files x86",)),
    ("shell_program_files_common", "Common Files folder", "ProgramFilesCommon", ("common files",)),
    ("shell_program_data", "ProgramData folder", "Common AppData", ("programdata",)),
    ("shell_profile", "User profile folder", "Profile", ("user folder", "home folder")),
    ("shell_user_profiles", "Users folder", "UserProfiles", ("users folder",)),
    ("shell_public", "Public folder", "Public", ("public folder",)),
    ("shell_common_desktop", "Public Desktop", "Common Desktop", ("public desktop",)),
    ("shell_common_documents", "Public Documents", "Common Documents", ("public documents",)),
    ("shell_favorites", "Favorites folder", "Favorites", ("favourites",)),
    ("shell_links", "Links folder", "Links", ("links",)),
    ("shell_templates", "Templates folder", "Templates", ("templates",)),
    ("shell_saved_games", "Saved Games folder", "SavedGames", ("saved games", "game saves")),
    ("shell_screenshots", "Screenshots folder", "Screenshots", ("screenshots", "screenshot folder")),
    ("shell_camera_roll", "Camera Roll folder", "Camera Roll", ("camera roll",)),
    ("shell_captures", "Captures folder (Game Bar)", "Captures", ("game captures", "game bar recordings")),
    ("shell_onedrive", "OneDrive folder", "OneDrive", ("onedrive",)),
    ("shell_libraries", "Libraries", "Libraries", ("libraries",)),
    ("shell_apps_folder", "Applications (all installed apps)", "AppsFolder", ("all apps", "apps folder", "applications folder")),
    ("shell_recycle_bin", "Recycle Bin", "RecycleBinFolder", ("recycle bin", "trash", "deleted files")),
    ("shell_this_pc", "This PC", "MyComputerFolder", ("this pc", "my computer", "drives")),
    ("shell_network", "Network folder", "NetworkPlacesFolder", ("network computers", "network places")),
    ("shell_control_panel", "Control Panel (shell folder)", "ControlPanelFolder", ("control panel",)),
    ("shell_printers", "Printers folder", "PrintersFolder", ("printers folder",)),
    ("shell_connections", "Network Connections folder", "ConnectionsFolder", ("network connections folder",)),
    ("shell_change_remove_programs", "Programs and Features (shell)", "ChangeRemoveProgramsFolder", ("change remove programs",)),
    ("shell_installed_updates", "Installed Updates", "AppUpdatesFolder", ("installed updates", "uninstall update", "update history classic")),
    ("shell_admin_tools", "Administrative Tools folder (user)", "Administrative Tools", ("admin tools folder",)),
    ("shell_common_admin_tools", "Windows Tools folder (all users)", "Common Administrative Tools", ("windows tools folder",)),
    ("shell_credential_manager", "Credentials folder", "CredentialManager", ("credentials folder",)),
    ("shell_history", "Internet history folder", "History", ("browsing history folder",)),
    ("shell_cache", "Internet cache folder", "Cache", ("inetcache", "temporary internet files")),
    ("shell_cookies", "Cookies folder", "Cookies", ("cookies folder",)),
    ("shell_system_certificates", "System certificates folder", "SystemCertificates", ("certificate store folder",)),
    ("shell_contacts", "Contacts folder", "Contacts", ("contacts folder",)),
    ("shell_searches", "Saved Searches folder", "Searches", ("saved searches",)),
    ("shell_quick_launch", "Quick Launch folder", "Quick Launch", ("quick launch",)),
    ("shell_user_pinned", "Pinned items folder", "User Pinned", ("taskbar pinned folder",)),
    ("shell_account_pictures", "Account Pictures folder", "AccountPictures", ("account pictures", "profile picture folder")),
    ("shell_cd_burning", "CD Burning staging folder", "CD Burning", ("burn cd",)),
    ("shell_sync_center", "Sync Center folder", "SyncCenterFolder", ("sync center folder",)),
    ("shell_common_downloads", "Public Downloads", "CommonDownloads", ("public downloads",)),
    ("shell_user_program_files", "Per-user Programs folder", "UserProgramFiles", ("user programs folder", "appdata local programs")),
    ("shell_ringtones", "Ringtones folder", "Ringtones", ("ringtones",)),
    ("shell_device_metadata", "Device Metadata Store", "Device Metadata Store", ("device metadata",)),
]

# id, title, CLSID, aliases, availability
_SHELL_CLSID_ROWS = [
    ("clsid_god_mode", "All Tasks (God Mode)", "{ED7BA470-8E54-465E-825C-99712043E01C}", ("god mode", "godmode", "all tasks", "all settings list", "master control panel"), "Lists every Control Panel task."),
    ("clsid_all_control_panel_items", "All Control Panel Items", "{21EC2020-3AEA-1069-A2DD-08002B30309D}", ("all control panel items", "control panel icons view"), ""),
    ("clsid_control_panel_category", "Control Panel (category view)", "{26EE0668-A00A-44D7-9371-BEB064C98683}", ("control panel", "classic control panel", "control panel kholo"), ""),
    ("clsid_this_pc", "This PC (namespace)", "{20D04FE0-3AEA-1069-A2D8-08002B30309D}", ("my computer",), ""),
    ("clsid_recycle_bin", "Recycle Bin (namespace)", "{645FF040-5081-101B-9F08-00AA002F954E}", ("recycle bin",), ""),
    ("clsid_network", "Network (namespace)", "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}", ("network neighborhood",), ""),
    ("clsid_network_connections", "Network Connections (namespace)", "{7007ACC7-3202-11D1-AAD2-00805FC1270E}", ("network connections", "adapters"), ""),
    ("clsid_installed_updates", "Installed Updates (namespace)", "{d450a8a1-9568-45c7-9c0e-b4f9fb4537bd}", ("installed updates", "uninstall updates"), ""),
    ("clsid_windows_features", "Windows Features (namespace)", "{67718415-c450-4f3c-bf8a-b487642dc39b}", ("windows features",), ""),
    ("clsid_printers", "Printers (namespace)", "{2227A280-3AEA-1069-A2DE-08002B30309D}", ("printers",), ""),
    ("clsid_quick_access", "Home / Quick access", "{679f85cb-0220-4080-b29b-5540cc05aab6}", ("quick access", "explorer home"), ""),
    ("clsid_libraries", "Libraries (namespace)", "{031E4825-7B94-4dc3-B131-E946B44C8DD5}", ("libraries",), ""),
    ("clsid_frequent_folders", "Frequent folders", "{3936E9E4-D92C-4EEE-A85A-BC16D5EA0819}", ("frequent folders",), ""),
    ("clsid_recent_places", "Recent places", "{22877a6d-37a1-461a-91b0-dbda5aaebc99}", ("recent folders",), ""),
    ("clsid_applications", "Applications (namespace)", "{4234d49b-0245-4df3-b780-3893943456e1}", ("all apps",), ""),
    ("clsid_user_files", "User files folder (namespace)", "{59031a47-3f72-44a7-89c5-5595fe6b30ee}", ("user profile folder",), ""),
]

KINDS = ("ms_settings", "control_name", "cpl", "msc", "utility", "shell_folder", "shell_clsid")
RISKS = ("low", "controlled")
LIFECYCLES = ("supported", "conditional", "deprecated", "removed")
_KIND_LABELS = {
    "ms_settings": "Windows Settings page",
    "control_name": "Control Panel item",
    "cpl": "Control Panel applet",
    "msc": "management console",
    "utility": "Windows utility",
    "shell_folder": "File Explorer folder",
    "shell_clsid": "File Explorer namespace",
}
_CLSID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
_FILE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}\.(?:msc|cpl|exe)$", re.IGNORECASE)
_CANONICAL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{1,100}$")
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()\-]{0,79}$")
_PAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}$")
_CPL_SUFFIX_RE = re.compile(r"^(?:,,\d)?$")
_ARGUMENT_RE = re.compile(r"^[A-Za-z0-9_.,/ ]{1,80}$")


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def _entry(**fields: Any) -> dict[str, Any]:
    base = {
        "lifecycle": "supported", "aliases": [], "availability": "", "risk": "low",
        "minimum_build": None, "clsid": None, "file": None, "arguments": None,
        "page": None, "source": "static", "present": "unknown", "reference": None,
        "catalogue_version": CATALOGUE_VERSION,
    }
    base.update(fields)
    if base["clsid"]:
        base["clsid"] = base["clsid"].upper()
    return base


def _settings_entry(row: tuple) -> dict[str, Any]:
    identifier, category, label, uri, lifecycle, aliases, note, min_build = row
    aliases = tuple(aliases) + tuple(a for a in _HINGLISH.get(identifier, ()) if a not in aliases)
    entry = _entry(
        id=identifier, kind="ms_settings", category=category, title=label,
        target=f"ms-settings:{uri}", lifecycle=lifecycle, aliases=list(aliases),
        availability=note, minimum_build=min_build or None, reference=MICROSOFT_SOURCE,
        present=False if lifecycle == "removed" else "unknown",
    )
    # Compatibility fields used by the original Settings-only catalogue API.
    entry.update({"label": label, "uri": entry["target"], "uri_key": uri, "availability_note": note})
    return entry


def _build_static() -> tuple[dict[str, Any], ...]:
    out = [_settings_entry(row) for row in _ROWS]
    for ident, title, canonical, clsid, page, aliases, note, lifecycle in _CONTROL_NAME_ROWS:
        target = canonical + (f" /page {page}" if page else "")
        out.append(_entry(id=ident, kind="control_name", category="Control Panel", title=title,
                          target=target, canonical_name=canonical, page=page, clsid=clsid,
                          aliases=list(aliases), availability=note, lifecycle=lifecycle,
                          present=False if lifecycle == "removed" else "unknown"))
    for ident, title, file, suffix, aliases, note in _CPL_ROWS:
        out.append(_entry(id=ident, kind="cpl", category="Control Panel applets", title=title,
                          target=file + suffix, file=file, aliases=list(aliases), availability=note,
                          lifecycle="conditional" if note.startswith("Requires") else "supported"))
    for ident, title, file, aliases, note, risk in _MSC_ROWS:
        out.append(_entry(id=ident, kind="msc", category="Management consoles", title=title,
                          target=file, file=file, aliases=list(aliases), availability=note, risk=risk,
                          lifecycle="conditional" if note else "supported"))
    for ident, title, exe, args, aliases, note, risk in _UTILITY_ROWS:
        out.append(_entry(id=ident, kind="utility", category="System tools", title=title,
                          target=exe + (f" {args}" if args else ""), file=exe, arguments=args,
                          aliases=list(aliases), availability=note, risk=risk,
                          lifecycle="deprecated" if "Deprecated" in note else "supported"))
    for ident, title, name, aliases in _SHELL_FOLDER_ROWS:
        out.append(_entry(id=ident, kind="shell_folder", category="Folders", title=title,
                          target=f"shell:{name}", folder_name=name, aliases=list(aliases)))
    for ident, title, clsid, aliases, note in _SHELL_CLSID_ROWS:
        out.append(_entry(id=ident, kind="shell_clsid", category="Shell namespaces", title=title,
                          target=f"shell:::{clsid.upper()}", clsid=clsid, aliases=list(aliases),
                          availability=note))
    return tuple(out)


STATIC_SURFACES: tuple[dict[str, Any], ...] = _build_static()
SURFACES_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in STATIC_SURFACES}
SETTINGS_CATALOG: tuple[dict[str, Any], ...] = tuple(i for i in STATIC_SURFACES if i["kind"] == "ms_settings")
SETTINGS_BY_ID = {item["id"]: item for item in SETTINGS_CATALOG}


def validate_entry(entry: dict[str, Any]) -> None:
    """Raise ValueError unless an entry has a well-formed, non-free-form launch target."""
    kind = entry.get("kind")
    target = entry.get("target")
    if kind not in KINDS or not isinstance(target, str):
        raise ValueError(f"invalid kind or target for {entry.get('id')!r}")
    if entry.get("risk") not in RISKS or entry.get("lifecycle") not in LIFECYCLES:
        raise ValueError(f"invalid risk or lifecycle for {entry.get('id')!r}")
    if kind == "ms_settings":
        ok = re.fullmatch(r"ms-settings:[a-z0-9\-]*", target) is not None
    elif kind == "control_name":
        ok = bool(_CANONICAL_RE.match(entry.get("canonical_name") or "")) and (
            entry.get("page") is None or bool(_PAGE_RE.match(entry["page"])))
    elif kind == "cpl":
        file = entry.get("file") or ""
        ok = bool(_FILE_RE.match(file)) and file.lower().endswith(".cpl") and bool(
            _CPL_SUFFIX_RE.match(target[len(file):])) and target.startswith(file)
    elif kind == "msc":
        ok = bool(_FILE_RE.match(target)) and target.lower().endswith(".msc")
    elif kind == "utility":
        file = entry.get("file") or ""
        ok = bool(_FILE_RE.match(file)) and file.lower().endswith(".exe") and (
            entry.get("arguments") is None or bool(_ARGUMENT_RE.match(entry["arguments"])))
    elif kind == "shell_folder":
        ok = target.startswith("shell:") and bool(_FOLDER_RE.match(target[len("shell:"):]))
    else:
        ok = target.startswith("shell:::") and bool(_CLSID_RE.match(target[len("shell:::"):]))
    if entry.get("clsid") and not _CLSID_RE.match(entry["clsid"]):
        ok = False
    if not ok:
        raise ValueError(f"catalogue entry {entry.get('id')!r} has a malformed {kind} target")


for _item in STATIC_SURFACES:
    validate_entry(_item)


# --------------------------------------------------------------------------- ranking

_STOP_WORDS = frozenset({
    "settings", "setting", "page", "pages", "open", "show", "go", "to", "the", "my", "a", "an",
    "in", "on", "for", "of", "and", "please", "me", "want", "i", "how", "do", "where", "is",
    "can", "you", "find", "get", "give", "list", "url", "urls", "uri", "uris", "every", "all",
    "catalog", "catalogue", "total", "windows", "window", "this", "pc", "computer", "with",
    # common Hinglish/informal fillers
    "kholo", "kholna", "karo", "karna", "dikhao", "mujhe", "hai", "ka", "ki", "ke", "mera",
    "meri", "chahiye", "kaise", "kahan", "wala", "wali", "pe", "par", "se", "ko", "plz", "pls",
})


def _normalize(value: str) -> str:
    normalized = value.casefold().replace("wi-fi", "wifi").replace("wi fi", "wifi").replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(value: str, *, drop_stop_words: bool = False) -> list[str]:
    words = _normalize(value).split()
    if drop_stop_words:
        kept = [w for w in words if w not in _STOP_WORDS]
        words = kept or words
    return [_stem(w) for w in words]


@lru_cache(maxsize=4096)
def _index(identifier: str, title: str, aliases: tuple[str, ...], category: str,
           target: str) -> tuple[tuple[frozenset[str], float], ...]:
    target_text = target.replace("ms-settings:", " ").replace("shell:", " ").replace("Microsoft.", " ")
    target_text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", target_text)
    return (
        (frozenset(_tokens(title)), 3.0),
        (frozenset(t for alias in aliases for t in _tokens(alias)), 2.6),
        (frozenset(_tokens(identifier.replace("_", " "))), 2.0),
        (frozenset(_tokens(target_text)), 1.6),
        (frozenset(_tokens(category)), 1.0),
    )


def _token_match(token: str, word: str) -> float:
    if token == word:
        return 1.0
    if len(token) >= 3 and len(word) >= 3 and (word.startswith(token) or token.startswith(word)):
        return 0.75
    if len(token) >= 4 and abs(len(token) - len(word)) <= 3:
        matcher = SequenceMatcher(None, token, word)
        if matcher.real_quick_ratio() >= 0.78 and matcher.quick_ratio() >= 0.78:
            ratio = matcher.ratio()
            if ratio >= 0.78:
                return ratio * 0.7
    return 0.0


# Tiny tie-breaker so equally good matches prefer the modern/canonical surface.
_KIND_TIE_BREAK = {"ms_settings": 0.05, "msc": 0.04, "control_name": 0.03, "utility": 0.02, "cpl": 0.01}


def score_entry(query: str, entry: dict[str, Any]) -> tuple[float, str]:
    """Score a free-text query against an entry; returns (score, reason). 0 means no match."""
    q_tokens = _tokens(query, drop_stop_words=True)
    if not q_tokens:
        return 0.0, ""
    fields = _index(entry["id"], entry["title"], tuple(entry.get("aliases") or ()),
                    entry.get("category", ""), entry["target"])
    total = 0.0
    matched = 0
    for q in q_tokens:
        best = 0.0
        for words, weight in fields:
            for word in words:
                best = max(best, _token_match(q, word) * weight)
        if best > 0:
            matched += 1
        total += best
    coverage = matched / len(q_tokens)
    if coverage < 0.5 or (len(q_tokens) == 1 and coverage < 1):
        return 0.0, ""
    score = (total / len(q_tokens)) * (0.4 + 0.6 * coverage)
    reason = "token"
    phrase = " ".join(q_tokens)
    names = [entry["title"], *(entry.get("aliases") or ())]
    if "_" in query:  # the caller is quoting a catalogue id
        names.append(entry["id"].replace("_", " "))
    stripped = [" ".join(_tokens(name)) for name in names]
    if phrase in stripped:
        score += 3.0
        reason = "exact"
    elif any(f" {phrase} " in f" {name} " for name in stripped):
        score += 1.5
        reason = "phrase"
    else:
        best_ratio = max(SequenceMatcher(None, phrase, name).ratio() for name in stripped)
        if best_ratio >= 0.85:
            score += 1.0
            reason = "fuzzy"
    if entry.get("lifecycle") == "deprecated":
        score -= 0.6
    elif entry.get("lifecycle") == "removed":
        score -= 1.2
    elif entry.get("lifecycle") == "conditional":
        score -= 0.1
    if entry.get("present") is False:
        score -= 0.8
    score += _KIND_TIE_BREAK.get(entry.get("kind", ""), 0.0)
    return max(score, 0.0), reason


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: (list(value) if isinstance(value, (list, tuple)) else value)
            for key, value in entry.items() if not key.startswith("_")}


def rank_surfaces(query: str, entries: Iterable[dict[str, Any]], *, kinds: Iterable[str] | None = None,
                  category: str | None = None, include_deprecated: bool = False,
                  limit: int = 15, min_score: float = 0.6) -> list[dict[str, Any]]:
    """Rank entries by token overlap, prefix and fuzzy similarity; returns copies with scores."""
    kind_set = set(kinds) if kinds else None
    category_key = _normalize(category) if category else None
    ranked: list[tuple[float, str, str, dict[str, Any]]] = []
    for entry in entries:
        if kind_set and entry["kind"] not in kind_set:
            continue
        if category_key and _normalize(entry.get("category", "")) != category_key:
            continue
        if not include_deprecated and entry.get("lifecycle") in {"deprecated", "removed"}:
            continue
        score, reason = score_entry(query, entry)
        if score >= min_score:
            ranked.append((score, reason, entry["id"], entry))
    ranked.sort(key=lambda row: (-row[0], row[2]))
    output = []
    for score, reason, _identifier, entry in ranked[:limit]:
        item = public_entry(entry)
        item["score"] = round(score, 3)
        item["match"] = reason
        output.append(item)
    return output


def _validate_limit(limit: int, maximum: int = 50) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")


# --------------------------------------------------------------- Settings-only compat API

def list_settings_pages(*, category: str | None = None, include_deprecated: bool = True,
                        limit: int = 40, offset: int = 0) -> dict[str, Any]:
    _validate_limit(limit)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    category_key = _normalize(category) if category else None
    records = [
        item for item in SETTINGS_CATALOG
        if (category_key is None or _normalize(item["category"]) == category_key)
        and (include_deprecated or item["lifecycle"] not in {"deprecated", "removed"})
    ]
    page = records[offset:offset + limit]
    return {
        "pages": [public_entry(item) for item in page],
        "count": len(page),
        "total_matching": len(records),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(records) else None,
        "categories": settings_categories(),
        "catalogue_version": CATALOGUE_VERSION,
        "source": MICROSOFT_SOURCE,
        "limitations": [
            "URI catalogue, not a guarantee that every page exists on every Windows build or SKU.",
            "Hardware-, policy-, account- and feature-dependent pages may be unavailable on this PC.",
            "Parameterized device/app deep links are listed but arbitrary URI query strings are not accepted.",
            "Control Panel items, consoles, utilities and shell folders are searchable with senti_search_windows_surfaces.",
        ],
    }


def settings_categories() -> list[str]:
    return sorted({item["category"] for item in SETTINGS_CATALOG})


def search_settings_pages(query: str = "", *, category: str | None = None,
                          include_deprecated: bool = False, limit: int = 15) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError("query must contain at most 160 characters")
    _validate_limit(limit)
    if not _tokens(query, drop_stop_words=True):
        listing = list_settings_pages(category=category, include_deprecated=include_deprecated, limit=limit)
        matches, total = listing["pages"], listing["total_matching"]
    else:
        matches = rank_surfaces(query, SETTINGS_CATALOG, category=category,
                                include_deprecated=include_deprecated, limit=500)
        total = len(matches)
        matches = matches[:limit]
    return {
        "matches": matches,
        "count": len(matches),
        "total_matches": total,
        "query": query,
        "category": category,
        "catalogue_version": CATALOGUE_VERSION,
        "source": MICROSOFT_SOURCE,
    }


class SurfaceLookupError(LookupError, ValueError):
    """Raised when a target does not identify exactly one catalogue entry."""


def _suggest(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": item["id"], "title": item["title"], "kind": item["kind"], "target": item["target"]}
            for item in rows]


def resolve_exact(target: str, entries: Iterable[dict[str, Any]], *,
                  kinds: Iterable[str] | None = None) -> dict[str, Any]:
    """Resolve an exact id, launch target, title or alias. Never auto-picks a fuzzy match."""
    if not isinstance(target, str) or not 1 <= len(target.strip()) <= 160:
        raise ValueError("target must contain 1 to 160 characters")
    kind_set = set(kinds) if kinds else None
    pool = [item for item in entries if kind_set is None or item["kind"] in kind_set]
    supplied = target.strip()
    for item in pool:
        if item["id"] == supplied:
            return item
    lowered = supplied.casefold()
    by_target = [item for item in pool if item["target"].casefold() == lowered]
    candidates = by_target
    if not candidates:
        normalized = _normalize(supplied)
        trimmed = re.sub(r"\b(?:settings?|page)\b", " ", normalized).strip()
        trimmed = re.sub(r"\s+", " ", trimmed)
        keys = {normalized, trimmed} - {""}
        for item in pool:
            names = [item["title"], *(item.get("aliases") or ())]
            if item["kind"] == "ms_settings":
                names.append(item["target"][12:])
            if any(_normalize(name) in keys for name in names if name):
                candidates.append(item)
    unique = {item["id"]: item for item in candidates}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        raise SurfaceLookupError(
            "Target name is ambiguous; choose one exact id: " + str(_suggest(list(unique.values())[:6])))
    suggestions = rank_surfaces(supplied.removeprefix("ms-settings:"), pool, include_deprecated=True, limit=5)
    raise SurfaceLookupError(
        "Target is not an exact entry in the SENTI Windows surface catalogue (allowlist). Search first and "
        f"pass an exact id; candidate_count={len(suggestions)}; suggestions={_suggest(suggestions)}")


def resolve_settings_page(target: str) -> dict[str, Any]:
    return resolve_exact(target, SETTINGS_CATALOG)


def catalogue_counts(entries: Iterable[dict[str, Any]] = STATIC_SURFACES) -> dict[str, int]:
    counts: dict[str, int] = {kind: 0 for kind in KINDS}
    for item in entries:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    counts["total"] = sum(counts[kind] for kind in KINDS)
    return counts
