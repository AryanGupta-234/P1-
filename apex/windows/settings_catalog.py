"""Curated, version-aware catalogue of documented Windows ms-settings URIs.

Source: Microsoft Learn, "Launch Windows Settings" URI scheme reference.
Only entries in this catalogue can be launched by APEX. Parameterized and
undocumented URI forms are intentionally not accepted as arbitrary input.
"""
from __future__ import annotations

import re
from typing import Any

MICROSOFT_SOURCE = (
    "https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings"
)
CATALOGUE_VERSION = 1

# id, category, label, URI, lifecycle, aliases, availability note, minimum build
# Lifecycle: supported, conditional, deprecated, removed.
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
    ("app_features_detail", "Apps", "Per-app features and options", "appsfeatures-app", "conditional", ("app advanced options", "app features", "manage app permissions", "reset app"), "Microsoft documents an optional package-family-name parameter to target a specific app; APEX only opens the base page and does not accept arbitrary URI parameters.", 0),
    ("apps_for_websites", "Apps", "Apps for websites", "appsforwebsites", "supported", ("website apps",), "", 0),
    ("default_apps", "Apps", "Default apps", "defaultapps", "conditional", ("default application", "file associations", "default browser"), "Per-application deep link parameters are supported only on qualifying Windows 11 builds; APEX does not accept arbitrary query strings.", 22000),
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
    ("sound_device_properties", "Sound", "Specific sound device properties (parameter required)", "sound-properties", "conditional", ("sound endpoint properties", "audio endpoint properties"), "Requires a device endpointId or interfaceId. APEX intentionally does not accept raw URI query strings for this page.", 0),

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
    ("energy_recommendations", "System", "Energy recommendations", "energyrecommendations", "conditional", ("energy settings",), "Microsoft documents availability from Windows 11 22H2 build 22624/F​​ebruary Moment update.", 22624),
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

def _record(row: tuple) -> dict[str, Any]:
    identifier, category, label, uri, lifecycle, aliases, note, min_build = row
    return {
        "id": identifier,
        "category": category,
        "label": label,
        "uri": f"ms-settings:{uri}",
        "uri_key": uri,
        "lifecycle": lifecycle,
        "aliases": list(aliases),
        "availability_note": note,
        "minimum_build": min_build or None,
        "source": "Microsoft Learn",
        "catalogue_version": CATALOGUE_VERSION,
    }


SETTINGS_CATALOG: tuple[dict[str, Any], ...] = tuple(_record(row) for row in _ROWS)
SETTINGS_BY_ID = {item["id"]: item for item in SETTINGS_CATALOG}


def _normalize(value: str) -> str:
    normalized = value.casefold().replace("wi-fi", "wifi").replace("wi fi", "wifi")
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def list_settings_pages(*, category: str | None = None, include_deprecated: bool = True,
                        limit: int = 40, offset: int = 0) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    category_key = _normalize(category) if category else None
    records = [
        item for item in SETTINGS_CATALOG
        if (category_key is None or _normalize(item["category"]) == category_key)
        and (include_deprecated or item["lifecycle"] not in {"deprecated", "removed"})
    ]
    return {
        "pages": [dict(item) for item in records[offset:offset + limit]],
        "count": len(records[offset:offset + limit]),
        "total_matching": len(records),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(records) else None,
        "categories": sorted({item["category"] for item in SETTINGS_CATALOG}),
        "catalogue_version": CATALOGUE_VERSION,
        "source": MICROSOFT_SOURCE,
        "limitations": [
            "Documented URI catalogue, not a guarantee that every page exists on every Windows build or SKU.",
            "Hardware-, policy-, account- and feature-dependent pages may be unavailable on this PC.",
            "Parameterized device/app deep links are listed but arbitrary URI query strings are not accepted.",
        ],
    }


def search_settings_pages(query: str = "", *, category: str | None = None,
                          include_deprecated: bool = False, limit: int = 15) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError("query must contain at most 160 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    stop_words = {"settings", "setting", "page", "pages", "windows", "open", "show", "go", "to", "the", "my", "all", "url", "urls", "uri", "uris", "catalog", "catalogue", "list", "get", "give", "every", "total"}
    terms = set(_normalize(query).split()) - stop_words
    category_key = _normalize(category) if category else None
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for item in SETTINGS_CATALOG:
        if category_key and _normalize(item["category"]) != category_key:
            continue
        if not include_deprecated and item["lifecycle"] in {"deprecated", "removed"}:
            continue
        haystack = _normalize(" ".join([
            item["id"], item["category"], item["label"], item["uri_key"], *item["aliases"],
        ]))
        words = set(haystack.split())
        score = 0
        if terms and not terms.issubset(words) and not all(
            any(term in word for word in words) for term in terms
        ):
            continue
        if terms:
            score += 8 * len(terms & words)
            if _normalize(item["label"]) == _normalize(query):
                score += 20
            if _normalize(item["id"]) == _normalize(query):
                score += 30
            if item["uri_key"].replace("-", " ") == _normalize(query):
                score += 18
        else:
            score = 1
        if item["lifecycle"] == "supported":
            score += 2
        ranked.append((score, item["id"], item))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    matches = [dict(row[2]) for row in ranked[:limit]]
    return {
        "matches": matches,
        "count": len(matches),
        "total_matches": len(ranked),
        "query": query,
        "category": category,
        "catalogue_version": CATALOGUE_VERSION,
        "source": MICROSOFT_SOURCE,
    }


def resolve_settings_page(target: str) -> dict[str, Any]:
    if not isinstance(target, str) or not 1 <= len(target.strip()) <= 160:
        raise ValueError("target must contain 1 to 160 characters")
    supplied = target.strip()
    if supplied.casefold().startswith("ms-settings:"):
        supplied = supplied[len("ms-settings:"):]
    normalized = _normalize(supplied)
    exact = []
    for item in SETTINGS_CATALOG:
        candidates = [item["id"], item["label"], item["uri_key"], *item["aliases"]]
        if any(_normalize(candidate) == normalized for candidate in candidates):
            exact.append(item)
    if not exact:
        # Only permit unique fuzzy resolution; callers can use search for alternatives.
        results = search_settings_pages(supplied, limit=5)["matches"]
        if len(results) == 1:
            exact = [SETTINGS_BY_ID[results[0]["id"]]]
        else:
            suggestions = [{"id": item["id"], "label": item["label"], "uri": item["uri"]}
                           for item in results[:5]]
            raise LookupError(
                "Settings page was not uniquely identified. Use apex_search_settings_pages; "
                f"candidate_count={len(results)}; suggestions={suggestions}"
            )
    if len(exact) > 1:
        unique_ids = {item["id"] for item in exact}
        if len(unique_ids) > 1:
            suggestions = [{"id": item["id"], "label": item["label"], "uri": item["uri"]}
                           for item in exact[:5]]
            raise LookupError(f"Settings page name is ambiguous; choose one exact page ID: {suggestions}")
    return dict(exact[0])
