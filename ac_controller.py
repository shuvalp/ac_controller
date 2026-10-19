
import asyncio

from greeclimate.device import Device, FanSpeed, Mode, TemperatureUnits
from greeclimate.discovery import Discovery


def enum_label(enum_type, value):
    if value is None:
        return "Unknown"
    try:
        return enum_type(value).name.replace("MediumLow", "Medium low").replace(
            "MediumHigh", "Medium high"
        )
    except ValueError:
        return f"Unknown ({value})"


def temperature_label(value, units):
    if value is None or units not in (TemperatureUnits.C, TemperatureUnits.F):
        return "Unknown"
    return f"{value:g} °{TemperatureUnits(units).name}"


def print_table(rows):
    headers = ("Device", "IP address", "Power", "Mode", "Room temp", "Target temp", "Fan", "Status")
    rows = [headers, *rows]
    # Keep device-provided names and error messages on one terminal line.
    rows = [[" ".join(str(cell).split()) for cell in row] for row in rows]
    widths = [max(len(row[index]) for row in rows) for index in range(len(headers))]
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(separator)
    for index, row in enumerate(rows):
        print("| " + " | ".join(cell.ljust(width) for cell, width in zip(row, widths)) + " |")
        if index == 0:
            print(separator)
    print(separator)


async def main():
    discovery = Discovery()

    try:
        devices = await discovery.scan(wait_for=5)
        print(f"Found {len(devices)} AC device(s)")

        rows = []
        for info in devices:
            device = Device(info)
            try:
                await device.bind()
                await device.update_state()

                # # Turn on cooling at 24°C
                # device.power = True
                # device.mode = Mode.Cool
                # device.temperature_units = TemperatureUnits.C
                # device.target_temperature = 24

                # await device.push_state_update()
                rows.append((
                    info.name, info.ip,
                    "Unknown" if device.power is None else "On" if device.power else "Off",
                    enum_label(Mode, device.mode),
                    temperature_label(device.current_temperature, device.temperature_units),
                    temperature_label(device.target_temperature, device.temperature_units),
                    enum_label(FanSpeed, device.fan_speed),
                    "Connected" if device.has_valid_state else "No state received",
                ))

            except Exception as exc:
                rows.append((info.name, info.ip, "Unknown", "Unknown", "Unknown", "Unknown", "Unknown", f"Error: {exc}"))
            finally:
                device.close()
        if rows:
            print_table(rows)
    finally:
        discovery.close()


if __name__ == "__main__":
    asyncio.run(main())
