"""Functions to manage the interface with a Shelly Smart Switch."""

import json
import platform
import subprocess
import time
from datetime import datetime

import requests

REFERENCE_TIME_STR = "2025-04-01 00:00:00"
GENERATE_ENERGY_DATA = False

logger_function = None
config_object = None
config_settings = None
scheduler_state = None



class ShellySwitchState:
    """Represents the state of a Shelly switch."""

    def __init__(self, config, logger, shelly_state_json=None):
        """
        Initializes the ShellySwitchState object.

        :param shelly_state_json: The JSON object representing the Shelly switch state. If None, it will use the debug file.
        """
        self.config = config
        self.logger = logger
        local_tz = datetime.now().astimezone().tzinfo
        self.debug_file = "SwitchStateDebug.json"

        # Initialise to off with some sensible values
        self.switch_state = {
            "SwitchID": 0,
            "Enabled": False,
            "SwitchStateStr": "off",
            "PowerDraw": 0,
            "Voltage": None,
            "Current": None,
            "EnergyUsed": 0,
            "Temperature": None,
        }

        if shelly_state_json is None:
            # We're in debug mode - try reading from file
            file_path = self.config.select_file_location(self.debug_file)
            if file_path.exists():
                try:
                    with file_path.open(encoding="utf-8") as file:
                        self.switch_state = json.load(file)
                        self.logger.log_message(
                            f"Shelly switch is disabled. Returning switch status from debug file as {self.switch_state['SwitchStateStr']}.",
                            "debug",
                        )
                except json.JSONDecodeError as e:
                    self.logger.log_fatal_error(f"Error reading Shelly switch debug file: {e}")
            else:
                self.logger.log_message(
                    f"Shelly switch is disabled. Returning default switch status of {self.switch_state['SwitchStateStr']}.",
                    "debug",
                )

            # Used secs elapsed since reference datetime to fake out current energy usage reading from switch
            if GENERATE_ENERGY_DATA:
                reference_time = datetime.strptime(
                    REFERENCE_TIME_STR, "%Y-%m-%d %H:%M:%S",
                ).astimezone(local_tz)
                self.switch_state["EnergyUsed"] = (
                    int((datetime.now(local_tz) - reference_time).total_seconds())
                    * 0.27777778
                )
            else:
                self.switch_state["EnergyUsed"] = 0

    def save_to_file(self):
        """
        Saves the current switch state to the debug file.

        :return: The current switch state.
        """
        file_path = self.config.select_file_location(self.debug_file)
        self.switch_state["SwitchStateStr"] = (
            "on" if self.switch_state["Enabled"] else "off"
        )
        with file_path.open("w", encoding="utf-8") as file:
            json.dump(self.switch_state, file, indent=4)
            self.logger.log_message(
                f"Shelly switch is disabled. Saving status of {self.switch_state['SwitchStateStr']} to the {file_path}.",
                "debug",
            )
        return self.switch_state

    def record_switch_info(
        self,
        is_on: bool,  # noqa: FBT001
        power: float,
        voltage: float,
        current: float,
        energy_used: float,
        temperature: float,
    ):
        """
        Records the switch information.

        :param switch_info: The switch information to record.
        """
        self.switch_state["SwitchID"] = self.config.get("ShellySmartSwitch", "SwitchID")
        self.switch_state["Enabled"] = is_on
        self.switch_state["SwitchStateStr"] = "on" if is_on else "off"
        self.switch_state["PowerDraw"] = power
        self.switch_state["Voltage"] = voltage
        self.switch_state["Current"] = current
        self.switch_state["EnergyUsed"] = energy_used
        self.switch_state["Temperature"] = temperature


class ShellySwitch:
    """Represents a Shelly switch."""

    def __init__(self, config, logger):
        """Initializes the ShellySwitch object."""
        self.config = config
        self.logger = logger
        self.RETRY_COUNT = 3
        self.RETRY_DELAY = 2  # Delay in seconds between retries
        self.ip_address = self.config.get("ShellySmartSwitch", "IPAddress")
        self.switch_id = self.config.get("ShellySmartSwitch", "SwitchID")

        # See if the switch is alive
        self.switch_online = True
        if not self.config.get("ShellySmartSwitch", "DisableSwitch"):
            self.switch_online = self.ping_host(
                self.ip_address, timeout=self.config.get("ShellySmartSwitch", "Timeout"),
            )

    def ping_host(self, ip_address, timeout=1):
        """
        Pings an IP address and returns True if the host is responding, False otherwise.

        :param ip_address: The IP address to ping.
        :param timeout: Timeout in seconds for the ping response.
        :return: True if the host responds, False otherwise.
        """
        # Determine the ping command based on the operating system
        param = "-n" if platform.system().lower() == "windows" else "-c"
        command = ["ping", param, "1", "-W", str(timeout), ip_address]

        try:
            # Run the ping command
            response = subprocess.run(command, capture_output=True, check=False)  # noqa: S603
        except (subprocess.CalledProcessError, OSError) as e:
            self.logger.log_message(f"Error pinging {ip_address}: {e}", "debug")
            return False
        else:
            # Return True if the ping was successful (exit code 0)
            return response.returncode == 0

    def get_status(self):
        """Return a switch_state dict or None on error for any supported switch."""
        if self.config.get("ShellySmartSwitch", "DisableSwitch"):
            # If we are in debug mode, return the value held in the debugfile or defaults otherwise
            switch = ShellySwitchState(self.config, self.logger)
            return switch.switch_state

        if self.switch_online is False:
            self.logger.log_message(
                f"Shelly switch at {self.ip_address} is offline, skipping getting status.",
                "debug",
            )
            return None

        fatal_error = None
        switch_state = None

        for attempt in range(self.RETRY_COUNT):
            if self.config.get("ShellySmartSwitch", "Model") == "ShellyEM":
                switch_state, fatal_error = self.get_gen1_em_status()
            elif (
                self.config.get("ShellySmartSwitch", "Model") == "ShellyPlus1PM"
                or self.config.get("ShellySmartSwitch", "Model") == "Shelly1PMG3"
            ):
                switch_state, fatal_error = self.get_gen2_switch_status()
            else:
                self.logger.log_fatal_error(
                    f"Unsupported Shelly switch model: {self.config.get('ShellySmartSwitch', 'Model')}",
                )

            if switch_state is None:
                # Log the failure
                self.logger.log_message(
                    f"Shelly switch at {self.ip_address} reported error {fatal_error} when getting status. Attempt {attempt + 1} of {self.RETRY_COUNT}.",
                    "error",
                )
                time.sleep(self.RETRY_DELAY)
            else:
                return switch_state

        # If we get here, we have failed to get the status after 3 attempts. Terminate
        self.logger.log_fatal_error(fatal_error)
        return None

    def get_gen1_em_status(self):
        """Return a switch_state dict object and an error string, or None on error."""
        fatal_error = None
        self.logger.log_message(
            f"Getting status of Shelly Energy Meter {self.switch_id} at {self.ip_address}...",
            "debug",
        )

        url = f"http://{self.ip_address}/status"
        headers = {
            "Content-Type": "application/json",
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=self.config.get("ShellySmartSwitch", "Timeout"),
            )
            response.raise_for_status()
            response_payload = response.json()

            # Create a ShellySwitchState object with the response payload
            switch = ShellySwitchState(self.config, self.logger)

            # And populate with the returned payload
            switch.record_switch_info(
                is_on=response_payload["relays"][self.switch_id]["ison"],
                power=response_payload["emeters"][0]["power"],
                voltage=response_payload["emeters"][0]["voltage"],
                current=None,
                energy_used=response_payload["emeters"][0]["total"],
                temperature=None,
            )

            self.logger.log_message(
                f"Shelly energy meter relay at {self.ip_address} is currently {switch.switch_state['SwitchStateStr']}",
                "debug",
            )
            return switch.switch_state, fatal_error

        except (
            requests.exceptions.ConnectionError
        ) as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error fetching Shelly energy meter status: {e}"

        except (
            requests.exceptions.Timeout
        ) as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error fetching Shelly energy meter status: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error fetching Shelly energy meter status: {e}"

        except KeyError as e:
            fatal_error = f"Key error in response payload from Shelly energy meter: {e}"

        else:
            self.logger.log_message(
                f"Shelly energy meter relay at {self.ip_address} is currently {switch.switch_state['SwitchStateStr']}",
                "debug",
            )
            return switch.switch_state, fatal_error

        return None, fatal_error

    def get_gen2_switch_status(self):
        """Return a switch_state dict for a gen2/gen3 Shelly Switch and error message or None on error."""
        fatal_error = None
        # Example JSON object returned from Gen2/3 Shelly Switch looks like this:
        #     "id": 0,
        #     "source": "HTTP_in",
        #     "output": false,
        #     "apower": 0.0,
        #     "voltage": 245.0,
        #     "current": 0.000,
        #     "aenergy": {
        #         "total": 23984.169,
        #         "by_minute": [
        #         0.000,
        #         0.000,
        #         0.000
        #         ],
        #         "minute_ts": 1743480180
        #     },
        #     "temperature": {
        #         "tC": 50.2,
        #         "tF": 122.4
        #     }

        self.logger.log_message(
            f"Getting status of Shelly Gen2/3 switch {self.switch_id} at {self.ip_address}...",
            "debug",
        )

        url = f"http://{self.ip_address}/rpc"
        headers = {
            "Content-Type": "application/json",
        }

        payload = {
            "id": 0,
            "method": "switch.GetStatus",
            "params": {
                "id": self.switch_id,
            },
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.config.get("ShellySmartSwitch", "Timeout"),
            )
            response_payload = response.json()

            # Create a ShellySwitchState object with the response payload
            switch = ShellySwitchState(self.config, self.logger)

            # And populate with the returned payload
            switch.record_switch_info(
                is_on=response_payload["result"]["output"],
                power=response_payload["result"]["apower"],
                voltage=response_payload["result"]["voltage"],
                current=response_payload["result"]["current"],
                energy_used=response_payload["result"]["aenergy"]["total"],
                temperature=response_payload["result"]["temperature"]["tC"],
            )

            self.logger.log_message(
                f"Shelly switch {self.switch_id} at {self.ip_address} is currently {switch.switch_state['SwitchStateStr']}",
                "debug",
            )

        except (
            requests.exceptions.ConnectionError
        ) as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error fetching Shelly switch status: {e}"

        except (
            requests.exceptions.Timeout
        ) as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error fetching Shelly switch status: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error fetching Shelly switch status: {e}"

        except KeyError as e:
            fatal_error = f"Key error in response payload from Shelly switch: {e}"
        else:
            return switch.switch_state, None

        return None, fatal_error

    def change_switch(self, turn_on: bool):  # noqa: FBT001
        """
        Turn a Shelly switch on or off.

        :param turn_on: True to turn on the switch, False to turn it off.
        :return: True if the switch was successfully turned on or off, False otherwise.
        """
        local_tz = datetime.now().astimezone().tzinfo
        if self.config.get("ShellySmartSwitch", "DisableSwitch"):
            # If in debug mode, just save the new state to file
            switch = ShellySwitchState(self.config, self.logger)

            # Used secs elapsed since reference datetime to fake out current energy usage reading from switch
            reference_time = datetime.strptime(
                REFERENCE_TIME_STR, "%Y-%m-%d %H:%M:%S",
            ).astimezone(local_tz)
            switch.switch_state["EnergyUsed"] = (
                int((datetime.now(local_tz) - reference_time).total_seconds())
                * 0.27777778
            )
            switch.switch_state["Enabled"] = turn_on
            switch.save_to_file()
            return turn_on

        if self.switch_online is False:
            if turn_on:
                self.logger.log_fatal_error(
                    "Shelly switch asked to trun on when device is offline",
                    report_stack=True,
                )
            self.logger.log_message(
                f"Shelly switch at {self.ip_address} is offline, skipping state change.",
                "debug",
            )
            return turn_on

        fatal_error = None
        new_status = None

        for attempt in range(self.RETRY_COUNT):
            if self.config.get("ShellySmartSwitch", "Model") == "ShellyEM":
                new_status, fatal_error = self.change_gen1_em_switch(turn_on)
            elif (
                self.config.get("ShellySmartSwitch", "Model") == "ShellyPlus1PM"
                or self.config.get("ShellySmartSwitch", "Model") == "Shelly1PMG3"
            ):
                new_status, fatal_error = self.change_gen2_switch(turn_on)
            else:
                self.logger.log_fatal_error(
                    f"Unsupported Shelly switch model: {self.config.get('ShellySmartSwitch', 'Model')}",
                )

            if new_status is None:
                # Log the failure
                self.logger.log_message(
                    f"Shelly switch at {self.ip_address} reported error {fatal_error} when changing state. Attempt {attempt + 1} of {self.RETRY_COUNT}.",
                    "error",
                )
                time.sleep(self.RETRY_DELAY)
            else:
                return new_status

        # If we get here, we have failed to get the status after 3 attempts. Terminate
        self.logger.log_fatal_error(fatal_error)
        return None

    def change_gen1_em_switch(self, turn_on: bool):  # noqa: FBT001
        """
        Turn a Gen1 EM switch on or off.

        :param turn_on: True to turn on the switch, False to turn it off.
        """
        fatal_error = None
        self.logger.log_message(
            f"Starting the Shelly energy meter change state function for {self.switch_id} at {self.ip_address}. switch on: {turn_on}",
            "debug",
        )

        if turn_on:
            url = f"http://{self.ip_address}/relay/0?turn=on"
        else:
            url = f"http://{self.ip_address}/relay/0?turn=off"
        headers = {
            "Content-Type": "application/json",
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=self.config.get("ShellySmartSwitch", "Timeout"),
            )
            response.raise_for_status()
            response_payload = response.json()
            new_status = response_payload["ison"]

        except (
            requests.exceptions.ConnectionError
        ) as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error changing Shelly energy meter relay: {e}"

        except (
            requests.exceptions.Timeout
        ) as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error changing Shelly energy meter relay: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error changing Shelly energy meter relay: {e}"

        except KeyError as e:
            fatal_error = (
                f"Key error in response payload from Shelly energy meter relay: {e}"
            )

        if fatal_error is not None:
            return None, fatal_error

        if new_status != turn_on:
            self.logger.log_fatal_error(
                f"The new state of the Shelly energy meter relay was not as expected. Expected: {turn_on}, Actual: {new_status}",
            )

        new_status_str = "on" if new_status else "off"
        self.logger.log_message(
            f"Shelly energy meter relay at {self.ip_address} is {new_status_str}",
            "summary",
        )
        return turn_on, None

    def change_gen2_switch(self, turn_on: bool):  # noqa: FBT001
        """
        Turn a Gen2/3 switch on or off.

        :param turn_on: True to turn on the switch, False to turn it off.
        :return: True if the switch was successfully turned on or off, False otherwise.
        """
        fatal_error = None
        self.logger.log_message(
            f"Starting the Shelly switch change state function for {self.switch_id} at {self.ip_address}. switch on: {turn_on}",
            "debug",
        )

        url = f"http://{self.ip_address}/rpc"
        headers = {
            "Content-Type": "application/json",
        }

        payload = {
            "id": 0,
            "method": "switch.Set",
            "params": {
                "id": self.switch_id,
                "on": turn_on,
            },
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.config.get("ShellySmartSwitch", "Timeout"),
            )
            response_payload = response.json()
            prior_status = response_payload["result"]["was_on"]

        except (
            requests.exceptions.ConnectionError
        ) as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error changing Shelly switch state: {e}"

        except (
            requests.exceptions.Timeout
        ) as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error changing Shelly switch state: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error changing Shelly switch state: {e}"

        except KeyError as e:
            fatal_error = f"Key error in response payload from Shelly switch: {e}"

        if fatal_error is not None:
            return None, fatal_error

        prior_status_str = "on" if prior_status else "off"
        current_status_str = "on" if turn_on else "off"
        if prior_status != turn_on:
            self.logger.log_message(
                f"Changing Shelly switch {self.switch_id} at {self.ip_address} was {prior_status_str} and is now {current_status_str}",
                "summary",
            )
        else:
            self.logger.log_message(
                f"Shelly switch {self.switch_id} at {self.ip_address} remains {current_status_str}",
                "summary",
            )
        return turn_on, None
