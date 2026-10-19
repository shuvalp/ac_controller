"""Shared presentation and input validation, independent of GTK and networking."""

import math

BUS_NAME = "io.github.greeclimate.Controller"
OBJECT_PATH = "/io/github/greeclimate/Controller"
INTERFACE = "io.github.greeclimate.Controller1"
APP_ID = "io.github.greeclimate.Controller.Desktop"

MODES = {0: "Auto", 1: "Cool", 2: "Dry", 3: "Fan", 4: "Heat"}
FAN_SPEEDS = {0: "Auto", 1: "Low", 2: "Medium low", 3: "Medium", 4: "Medium high", 5: "High"}
HORIZONTAL_SWING = {
    0: "Default / off", 1: "Full swing", 2: "Left", 3: "Left center",
    4: "Center", 5: "Right center", 6: "Right",
}
VERTICAL_SWING = {
    0: "Default / off", 1: "Full swing", 2: "Upper", 3: "Upper middle",
    4: "Middle", 5: "Lower middle", 6: "Lower", 7: "Swing upper",
    8: "Swing upper middle", 9: "Swing middle", 10: "Swing lower middle",
    11: "Swing lower",
}
CHOICES = {
    "mode": MODES, "fan_speed": FAN_SPEEDS,
    "horizontal_swing": HORIZONTAL_SWING, "vertical_swing": VERTICAL_SWING,
}
FIELDS = ("power", "mode", "target_temperature", "temperature_units", "fan_speed",
          "horizontal_swing", "vertical_swing")


def clean_name(value):
    if not isinstance(value, str):
        raise ValueError("Name must be text.")
    value = " ".join(value.split())
    if len(value) > 80 or any(ord(char) < 32 for char in value):
        raise ValueError("Use a name of at most 80 printable characters.")
    return value


def temperature_bounds(units):
    return (46, 86) if units == 1 else (8, 30)


def temperature_text(value, units):
    if value is None or units not in (0, 1):
        return "Unknown"
    return f"{value:g} °{'F' if units == 1 else 'C'}"


def power_text(value):
    return "Unknown" if value is None else "On" if value else "Off"


def validate_settings(settings, state):
    if not isinstance(settings, dict) or not settings:
        raise ValueError("Supply at least one setting.")
    unknown = settings.keys() - set(FIELDS)
    if unknown:
        raise ValueError(f"Unsupported setting: {', '.join(sorted(unknown))}")
    for key, value in settings.items():
        if key == "power":
            if type(value) is not bool:
                raise ValueError("Power must be true or false.")
        elif key in CHOICES or key == "temperature_units":
            choices = CHOICES.get(key, {0: "C", 1: "F"})
            if type(value) is not int or value not in choices:
                raise ValueError(f"Invalid value for {key}.")
        elif key == "target_temperature":
            units = settings.get("temperature_units", state.get("temperature_units"))
            if units not in (0, 1):
                raise ValueError("Read the device's temperature units before changing its target.")
            lower, upper = temperature_bounds(units)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value != int(value) or not lower <= value <= upper):
                raise ValueError(f"Temperature must be a whole number between {lower} and {upper}.")
        if key in ("horizontal_swing", "vertical_swing") and state.get(key) is None:
            raise ValueError("This device has not reported support for that swing control.")
    return settings


INTROSPECTION_XML = f"""<node>
  <interface name="{INTERFACE}">
    <method name="GetSnapshot"><arg type="s" direction="out" name="snapshot"/></method>
    <method name="Scan"><arg type="s" direction="in" name="address"/>
      <arg type="s" direction="out" name="snapshot"/></method>
    <method name="SetDevice"><arg type="s" direction="in" name="device_id"/>
      <arg type="s" direction="in" name="settings"/>
      <arg type="s" direction="out" name="snapshot"/></method>
    <method name="RenameDevice"><arg type="s" direction="in" name="device_id"/>
      <arg type="s" direction="in" name="name"/>
      <arg type="s" direction="out" name="snapshot"/></method>
    <signal name="Changed"><arg type="s" name="snapshot"/></signal>
  </interface>
</node>"""
