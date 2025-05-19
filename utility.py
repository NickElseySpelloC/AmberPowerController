'''
PCUtility.py

Version: 10

Goal: Supporting clases for the main module.
'''
import json
import os
import sys
import platform
import subprocess
import traceback
import time
from datetime import datetime
import inspect
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import yaml
import requests
from cerberus import Validator

CONFIG_FILE = "PowerControllerConfig.yaml"
FATAL_ERROR_FILE = "FatalErrorTracking.txt"
REFERENCE_TIME_STR = "2025-04-01 00:00:00"
GENERATE_ENERGY_DATA = False

logger_function = None
config_object = None
config_settings = None
scheduler_state = None

def register_logger(logger):
    """
    Register the help functions and objects from the main module
    :param logger: A function that takes a message and a level as arguments.
    """
    global logger_function
    logger_function = logger

def register_configurator(configurator):
    """
    Register the help functions and objects from the main module
    :param configurator: The configuration settings object.
    """
    global config_object
    config_object = configurator
    global config_settings
    config_settings = configurator.get_config()

def register_scheduler_state(state):
    """
    Register the help functions and objects from the main module
    :param state: The scheduler state object.
    """
    global scheduler_state
    scheduler_state = state

def merge_configs(default, custom):
    """ Merges two dictionaries recursively, with the custom dictionary """

    for key, value in custom.items():
        if isinstance(value, dict) and key in default:
            merge_configs(default[key], value)
        else:
            default[key] = value
    return default

def send_email(subject, body):
    """Sends an email using Gmail SMTP server."""

    # Make sure we have a full configuration for email sending
    if config_settings["Email"]["EnableEmail"] is None or not config_settings["Email"]["EnableEmail"]:
        logger_function(f"SMTP settings not fully configured for sending emails. Skipping sending the email {subject}.", "debug")
        return

    # Load the Gmail SMTP server configuration
    send_to = config_settings["Email"]["SendEmailsTo"]
    smtp_server = config_settings["Email"]["SMTPServer"]
    smtp_port = config_settings["Email"]["SMTPPort"]
    sender_email = config_settings["Email"]["SMTPUsername"]
    app_password = config_settings["Email"]["SMTPPassword"]

    if any(not var for var in [send_to, smtp_server, smtp_port, sender_email, app_password]):
        report_fatal_error("SMTP configuration is incomplete. Please check the settings.")

    try:
        # Create the email
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = send_to
        if config_settings["Email"]["SubjectPrefix"] is not None:
            msg["Subject"] = config_settings["Email"]["SubjectPrefix"] + subject
        else:
            msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Connect to the Gmail SMTP server
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(sender_email, app_password)  # Log in using App Password
            server.sendmail(sender_email, send_to, msg.as_string())  # Send the email

    except RuntimeError as e:
        report_fatal_error(f"Failed to send email with subject {msg['Subject']}: {e}")

def report_fatal_error(message, report_stack=False, calling_function=None):
    """Report a fatal error and exit the program."""

    function_name = None
    if calling_function is None:
        stack = inspect.stack()
        # Get the frame of the calling function
        calling_frame = stack[1]
        # Get the function name
        function_name = calling_frame.function
        if function_name == "<module>":
            function_name = "main"
        # Get the class name (if it exists)
        class_name = None
        if "self" in calling_frame.frame.f_locals:
            class_name = calling_frame.frame.f_locals["self"].__class__.__name__
            full_reference = f"{class_name}.{function_name}()"
        else:
            full_reference = function_name + "()"
    else:
        full_reference = calling_function + "()"

    stack_trace = traceback.format_exc()
    if report_stack:
        message += f"\n\nStack trace:\n{stack_trace}"

    logger_function(f"Function {full_reference}: FATAL ERROR: {message}", "error")

    # Try to send an email
    if function_name != "send_email":
        # Don't send concurrent error emails
        if not fatal_error_tracking("get"):
            send_email("PowerController terminated with a fatal error", f"{message} \nAdditional emails will not be sent for concurrent errors - check the log file for more information. An email when be sent when the system recovers.")

    # record the error in in a file so that we keep track of this next time round
    fatal_error_tracking("set", message)

    # Exit the program
    sys.exit(1)

def fatal_error_tracking(mode, message = None):
    """Keep track of fatal errors by writing the last one to a file Used to keep track of 
    concurrent fatal errors
    :param mode: 
        "get": Returns True if the file exists, False otherwise
        "set": Writes the message to the file. If message is None, deletes the file.
    :param message: The message to write to the file. Only used in "set" mode.    
    """

    file_path = config_object.select_file_location(FATAL_ERROR_FILE)

    if mode == "get":
        # Check if the file exists
        if os.path.exists(file_path):
            return True
        else:
            return False
    elif mode == "set":
        # If message is None, delete the file
        if message is None:
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            else:
                return False
        else:
            # Write the message to the file
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(message)
            return True

def ping_host(ip_address, timeout=1):
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
        response = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        # Return True if the ping was successful (exit code 0)
        return response.returncode == 0
    except Exception as e:
        logger_function(f"Error pinging {ip_address}: {e}", "debug")
        return False


class ConfigManager:
    """
    Manages the configuration for the PowerController.
    Loads the configuration from a YAML file, validates it, and provides access to the configuration values.
    """
    def __init__(self):

        self.default_config = {
            "DeviceType": {
                "Type": "PoolPump",
                "Label": "Pool Pump",
                "WebsiteBaseURL": None,
                "WebsiteAccessKey": "<Your website API key here>"
            },
            "AmberAPI": {
                "APIKey": "<Your API Key Here>",
                "BaseUrl": "https://api.amber.com.au/v1",
                "Channel": "general",
                "Timeout": 10
            },
            "ShellySmartSwitch": {
                "Model": "Shelly1PMG3",
                "IPAddress": "<Your IP Here>",
                "SwitchID": 0,
                "DisableSwitch": False,
                "Timeout": 10
            },
            "DeviceRunScheule": {
                "MinimumRunHoursPerDay": 3,
                "MaximumRunHoursPerDay": 9,
                "TargetRunHoursPerDay": 6,
                "MaximumPriceToRun": 20,
                "ThresholdAboveCheapestPricesForMinumumHours": 1.1
            },
            "Files": {
                "SavedStateFile": "PowerControllerState.json",
                "RunLogFile": "PowerControllerRun.csv",
                "RunLogFileMaxLines": 480,
                "MonitoringLogFile": "PowerController.log",
                "MonitoringLogFileMaxLines": 5000,
                "LogFileVerbosity": "summary",
                "ConsoleVerbosity": "summary",
                "LatestPriceData": "LatestAmberPrices.json"
            },
            "Email": {
                "EnableEmail": False,
                "SendSummary": False,
                "DailyEnergyUseThreshold": 0,
                "SendEmailsTo": "<Your email address here>",
                "SMTPServer": "<Your SMTP server here>",
                "SMTPPort": None,
                "SMTPUsername": "<Your SMTP username here>",
                "SMTPPassword": "<Your SMTP password here>",
                "SubjectPrefix": None
            }
        }

        self.default_config_schema = {
            "DeviceType": {
                "type": "dict",
                "schema": {
                    "Type": {"type": "string", "required": True, "allowed": ["PoolPump", "HotWaterSystem"]},
                    "Label": {"type": "string", "required": True},
                    "WebsiteBaseURL": {"type": "string", "required": False, "nullable": True},
                    "WebsiteAccessKey": {"type": "string", "required": False, "nullable": True}
                }
            },
            "AmberAPI": {
                "type": "dict",
                "schema": {
                    "APIKey": {"type": "string", "required": True},
                    "BaseUrl": {"type": "string", "required": True},
                    "Channel": {"type": "string", "required": True, "allowed": ["general", "controlledLoad"]},
                    "Timeout": {"type": "number", "required": True, "min": 5, "max": 60}
                }
            },
            "ShellySmartSwitch": {
                "type": "dict",
                "schema": {
                    "Model": {
                        "type": "string",
                        "required": True,
                        "allowed": ["ShellyEM", "ShellyPlus1PM", "Shelly1PMG3"]
                    },
                    "IPAddress": {"type": "string", "required": True},
                    "SwitchID": {"type": "number", "required": True, "min": 0, "max": 3},
                    "DisableSwitch": {"type": "boolean", "required": False, "nullable": True},
                    "Timeout": {"type": "number", "required": True, "min": 5, "max": 60}
                }
            },
            "DeviceRunScheule": {
                "type": "dict",
                "schema": {
                    "MinimumRunHoursPerDay": {"type": "number", "required": True, "min": 1, "max": 12},
                    "MaximumRunHoursPerDay": {"type": "number", "required": True, "min": 2, "max": 20},
                    "TargetRunHoursPerDay": {"type": "number", "required": True, "min": 2, "max": 20},
                    "MaximumPriceToRun": {"type": "number", "required": True, "min": 10, "max": 500},
                    "ThresholdAboveCheapestPricesForMinumumHours": {"type": "number", "required": True, "min": 1.0, "max": 2.0},
                    "MonthlyTargetRunHoursPerDay": {
                        "type": "dict",
                        "required": False,
                        "nullable": True},
                    "NoRunPeriods": {
                        "type": "list",
                        "required": False,
                        "nullable": True,
                        "schema": {
                            "type": "dict",
                            "schema": {
                                "StartDate": {
                                    "type": "string",
                                    "required": False,
                                    "regex": r"^\d{4}-\d{2}-\d{2}$"  # Validates the format YYYY-MM-DD
                                },
                                "EndDate": {
                                    "type": "string",
                                    "required": False,
                                    "regex": r"^\d{4}-\d{2}-\d{2}$"  # Validates the format YYYY-MM-DD
                                }
                            }
                        }
                    }
                }
            },
            "Files": {
                "type": "dict",
                "schema": {
                    "SavedStateFile": {"type": "string", "required": True},
                    "RunLogFile": {"type": "string", "required": False, "nullable": True},
                    "RunLogFileMaxLines": {"type": "number", "min": 0, "max": 10000},
                    "MonitoringLogFile": {"type": "string", "required": False, "nullable": True},
                    "MonitoringLogFileMaxLines": {"type": "number", "min": 0, "max": 100000},
                    "LogFileVerbosity": {
                        "type": "string",
                        "required": True,
                        "allowed": ["none", "error", "warning", "summary", "detailed", "debug"]
                    },
                    "ConsoleVerbosity": {
                        "type": "string",
                        "required": True,
                        "allowed": ["error", "warning", "summary", "detailed", "debug"]
                    },
                    "LatestPriceData": {"type": "string", "required": False, "nullable": True}
                }
            },
            "Email": {
                "type": "dict",
                "schema": {
                    "EnableEmail": {"type": "boolean", "required": True},
                    "SendSummary": {"type": "boolean", "required": False, "nullable": True},
                    "DailyEnergyUseThreshold": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 50000},
                    "SendEmailsTo": {"type": "string", "required": False, "nullable": True},
                    "SMTPServer": {"type": "string", "required": False, "nullable": True},
                    "SMTPPort": {"type": "number", "required": False, "nullable": True, "min": 25, "max": 1000},
                    "SMTPUsername": {"type": "string", "required": False, "nullable": True},
                    "SMTPPassword": {"type": "string", "required": False, "nullable": True},
                    "SubjectPrefix": {"type": "string", "required": False, "nullable": True}
                }
            }
        }

        config_file_path = self.select_file_location(CONFIG_FILE)
        if not os.path.exists(config_file_path):
            with open(config_file_path, "w", encoding="utf-8") as file:
                yaml.dump(self.default_config, file)

        with open(config_file_path, "r", encoding="utf-8") as file:
            v = Validator()
            config_doc = yaml.safe_load(file)

            self.validate_no_placeholders(config_doc)

            if not v.validate(config_doc, self.default_config_schema):
                print(f"Error in configuration file: {v.errors}", file=sys.stderr)
                sys.exit(1)

        self.active_config = merge_configs(self.default_config, config_doc)

    def validate_no_placeholders(self, config_section, path=""):
        # Define expected placeholders
        placeholders = {
            '<Your Amber API key here>',
            '<Your SMTP username here>',
            '<Your SMTP password here>'
        }

        if isinstance(config_section, dict):
            for key, value in config_section.items():
                self.validate_no_placeholders(value, f"{path}.{key}" if path else key)
        elif isinstance(config_section, list):
            for idx, item in enumerate(config_section):
                self.validate_no_placeholders(item, f"{path}[{idx}]")
        else:
            if str(config_section).strip() in placeholders:
                print(f"ERROR: Config value at '{path}' is still set to placeholder: '{config_section}'", file=sys.stderr)
                print(f"Please update {CONFIG_FILE} with your actual credentials.", file=sys.stderr)
                sys.exit(1) 

    def select_file_location(self, file_name: str) -> str:
        """
        Selects the file location for the given file name.
        :param file_name: The name of the file to locate. 
        :return: The full path to the file. If the file does not exist in the current directory, it will look in the script directory.
        """

        current_dir = os.getcwd()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, file_name)
        if not os.path.exists(file_path):
            file_path = os.path.join(script_dir, file_name)
        return file_path

    def get_config(self):
        """
        Returns the active configuration.
        :return: The active configuration dictionary.
        """
        return self.active_config

    def is_no_run_today(self):
        """ Check if today is a no run day """

        # Get the current date
        date_today = datetime.today().strftime("%Y-%m-%d")

        # Get the no run periods from the config
        if "NoRunPeriods" in self.active_config["DeviceRunScheule"]:
            no_run_periods = self.active_config["DeviceRunScheule"]["NoRunPeriods"]

            # Check if today falls within any of the no run periods
            for period in no_run_periods:
                if period["StartDate"] <= date_today <= period["EndDate"]:
                    return True
        return False

    def get_target_hours(self, for_date=datetime.today()):
        """
        Returns the target run hours for the given date.
        :param for_date: The date for which to get the target run hours. Defaults to today.
        :return: The target run hours for the given date.
        """
        if for_date is None:
            for_date=datetime.today()

        if self.is_no_run_today():
            # If today is a no run day, return 0
            target_hours = 0
        elif self.active_config["DeviceType"]["Type"] == "HotWaterSystem":
            # For hot water systems, our target run time is 24 hours
            target_hours = 24
        else:
            # For pool pumps, we need to check the config for the target run hours

            target_hours = self.default_config["DeviceRunScheule"]["TargetRunHoursPerDay"]
            device_label = self.active_config["DeviceType"]["Label"]
            month = for_date.strftime("%B")

            if "MonthlyTargetRunHoursPerDay" in self.active_config["DeviceRunScheule"]:
                if month in self.active_config["DeviceRunScheule"]["MonthlyTargetRunHoursPerDay"]:
                    target_hours = self.active_config["DeviceRunScheule"]["MonthlyTargetRunHoursPerDay"][month]

            # Now make sure the override is within the min/max range
            if target_hours < self.default_config["DeviceRunScheule"]["MinimumRunHoursPerDay"]:
                target_hours = self.default_config["DeviceRunScheule"]["MinimumRunHoursPerDay"]
                if logger_function is not None:
                    logger_function(f"{device_label} target daily run hours for {month} are too short. Resetting to the minimum of {target_hours}", "warning")
            elif target_hours > self.default_config["DeviceRunScheule"]["MaximumRunHoursPerDay"]:
                target_hours = self.default_config["DeviceRunScheule"]["MaximumRunHoursPerDay"]
                if logger_function is not None:
                    logger_function(f"{device_label} target daily run hours for {month} are too long. Resetting to the maximum of {target_hours}", "warning")

        return target_hours

class ShellySwitchState:
    """
    Represents the state of a Shelly switch.
    """
    def __init__(self, shelly_state_json = None):
        """
        Initializes the ShellySwitchState object.
        :param shelly_state_json: The JSON object representing the Shelly switch state. If None, it will use the debug file.
        """
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
            "Temperature": None
        }

        if shelly_state_json is None:
            # We're in debug mode - try reading from file
            file_path = config_object.select_file_location(self.debug_file)
            if os.path.exists(file_path):

                try:
                    with open(file_path, "r", encoding="utf-8") as file:
                        self.switch_state = json.load(file)
                        logger_function(f"Shelly switch is disabled. Returning switch status from debug file as {self.switch_state['SwitchStateStr']}.", "debug")
                except json.JSONDecodeError as e:
                    report_fatal_error(f"Error reading Shelly switch debug file: {e}")
            else:
                logger_function(f"Shelly switch is disabled. Returning default switch status of {self.switch_state['SwitchStateStr']}.", "debug")

            # Used secs elapsed since reference datetime to fake out current energy usage reading from switch
            if GENERATE_ENERGY_DATA:
                reference_time = datetime.strptime(REFERENCE_TIME_STR, "%Y-%m-%d %H:%M:%S")
                self.switch_state["EnergyUsed"] = int((datetime.now() - reference_time).total_seconds()) * 0.27777778
            else:
                self.switch_state["EnergyUsed"] = 0
        return

    def save_to_file(self):
        """
        Saves the current switch state to the debug file.
        :return: The current switch state.
        """
        file_path = config_object.select_file_location(self.debug_file)
        self.switch_state["SwitchStateStr"] = "on" if self.switch_state["Enabled"] else "off"
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(self.switch_state, file, indent=4)
            logger_function(f"Shelly switch is disabled. Saving status of {self.switch_state['SwitchStateStr']} to the {file_path}.", "debug")
        return self.switch_state

    def record_switch_info(self, is_on: bool, power: float, voltage: float,
                           current: float, energy_used: float, temperature: float):
        """
        Records the switch information.
        :param switch_info: The switch information to record.
        """
        self.switch_state["SwitchID"] = config_settings["ShellySmartSwitch"]["SwitchID"]
        self.switch_state["Enabled"] = is_on
        self.switch_state["SwitchStateStr"] = "on" if is_on else "off"
        self.switch_state["PowerDraw"] = power
        self.switch_state["Voltage"] = voltage
        self.switch_state["Current"] = current
        self.switch_state["EnergyUsed"] = energy_used
        self.switch_state["Temperature"] = temperature

class ShellySwitch:
    """
    Represents a Shelly switch.
    """
    def __init__(self):
        """
        Initializes the ShellySwitch object.
        """
        self.RETRY_COUNT = 3
        self.RETRY_DELAY = 2    # Delay in seconds between retries
        self.ip_address = config_settings["ShellySmartSwitch"]["IPAddress"]
        self.switch_id = config_settings["ShellySmartSwitch"]["SwitchID"]

        # See if the switch is alive
        self.switch_online = True
        if not config_settings["ShellySmartSwitch"]["DisableSwitch"]:
            self.switch_online = ping_host(self.ip_address, timeout=config_settings["ShellySmartSwitch"]["Timeout"])

    def get_status(self):
        """ Return a switch_state dict or None on error for any supported switch """

        if config_settings["ShellySmartSwitch"]["DisableSwitch"]:
            # If we are in debug mode, return the value held in the debugfile or defaults otherwise
            switch = ShellySwitchState()
            return switch.switch_state

        if self.switch_online is False:
            logger_function(f"Shelly switch at {self.ip_address} is offline, skipping getting status.", "debug")
            return None

        fatal_error = None
        switch_state = None

        for attempt in range(self.RETRY_COUNT):
            if config_settings["ShellySmartSwitch"]["Model"] == "ShellyEM":
                switch_state, fatal_error = self.get_gen1_em_status()
            elif config_settings["ShellySmartSwitch"]["Model"] == "ShellyPlus1PM":
                switch_state, fatal_error = self.get_gen2_switch_status()
            elif config_settings["ShellySmartSwitch"]["Model"] == "Shelly1PMG3":
                switch_state, fatal_error = self.get_gen2_switch_status()
            else:
                report_fatal_error(f"Unsupported Shelly switch model: {config_settings['ShellySmartSwitch']['Model']}")

            if switch_state is None:
                #Log the failure
                logger_function(f"Shelly switch at {self.ip_address} reported error {fatal_error} when getting status. Attempt {attempt + 1} of {self.RETRY_COUNT}.", "error")
                time.sleep(self.RETRY_DELAY)
            else:
                return switch_state

        # If we get here, we have failed to get the status after 3 attempts. Terminate
        report_fatal_error(fatal_error)

    def get_gen1_em_status(self):
        """ Return a switch_state dict object and an error string, or None on error """

        fatal_error = None
        logger_function(f"Getting status of Shelly Energy Meter {self.switch_id} at {self.ip_address}...", "debug")

        url = f"http://{self.ip_address}/status"
        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=config_settings["ShellySmartSwitch"]["Timeout"])
            response.raise_for_status()
            response_payload = response.json()

            # Create a ShellySwitchState object with the response payload
            switch = ShellySwitchState()

            # And populate with the returned payload
            switch.record_switch_info(
                is_on=response_payload["relays"][self.switch_id]["ison"],
                power=response_payload["emeters"][0]["power"],
                voltage=response_payload["emeters"][0]["voltage"],
                current=None,
                energy_used=response_payload["emeters"][0]["total"],
                temperature=None
            )

            logger_function(f"Shelly energy meter relay at {self.ip_address} is currently {switch.switch_state['SwitchStateStr']}", "debug")
            return switch.switch_state, fatal_error

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error fetching Shelly energy meter status: {e}"

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error fetching Shelly energy meter status: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error fetching Shelly energy meter status: {e}"

        except KeyError as e:
            fatal_error = f"Key error in response payload from Shelly energy meter: {e}"

        return None, fatal_error

    def get_gen2_switch_status(self):
        """ Return a switch_state dict for a gen2/gen3 Shelly Switch and error message or None on error """

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

        logger_function(f"Getting status of Shelly Gen2/3 switch {self.switch_id} at {self.ip_address}...", "debug")

        url = f"http://{self.ip_address}/rpc"
        headers = {
            "Content-Type": "application/json"
        }

        payload = {
            "id": 0,
            "method": "switch.GetStatus",
            "params": {
                "id": self.switch_id
            }
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=config_settings["ShellySmartSwitch"]["Timeout"])
            response_payload = response.json()

            # Create a ShellySwitchState object with the response payload
            switch = ShellySwitchState()

            # And populate with the returned payload
            switch.record_switch_info(
                is_on=response_payload["result"]["output"],
                power=response_payload["result"]["apower"],
                voltage=response_payload["result"]["voltage"],
                current=response_payload["result"]["current"],
                energy_used=response_payload["result"]["aenergy"]["total"],
                temperature=response_payload["result"]["temperature"]["tC"]
            )

            logger_function(f"Shelly switch {self.switch_id} at {self.ip_address} is currently {switch.switch_state['SwitchStateStr']}", "debug")
            return switch.switch_state, None

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error fetching Shelly switch status: {e}"

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error fetching Shelly switch status: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error fetching Shelly switch status: {e}"

        except KeyError as e:
            fatal_error = f"Key error in response payload from Shelly switch: {e}"

        return None, fatal_error

    def change_switch(self, turn_on: bool):
        """ Turn a Shelly switch on or off
        :param turn_on: True to turn on the switch, False to turn it off.
        :return: True if the switch was successfully turned on or off, False otherwise.
        """
        if config_settings["ShellySmartSwitch"]["DisableSwitch"]:
            # If in debug mode, just save the new state to file
            switch = ShellySwitchState()

            # Used secs elapsed since reference datetime to fake out current energy usage reading from switch
            reference_time = datetime.strptime(REFERENCE_TIME_STR, "%Y-%m-%d %H:%M:%S")
            switch.switch_state["EnergyUsed"] = int((datetime.now() - reference_time).total_seconds()) * 0.27777778
            switch.switch_state["Enabled"] = turn_on
            switch.save_to_file()
            return turn_on

        if self.switch_online is False:
            if turn_on:
                report_fatal_error("Shelly switch asked to trun on when device is offline", report_stack=True)
            logger_function(f"Shelly switch at {self.ip_address} is offline, skipping state change.", "debug")
            return turn_on


        fatal_error = None
        new_status = None

        for attempt in range(self.RETRY_COUNT):
            if config_settings["ShellySmartSwitch"]["Model"] == "ShellyEM":
                new_status, fatal_error = self.change_gen1_em_switch(turn_on)
            elif config_settings["ShellySmartSwitch"]["Model"] == "ShellyPlus1PM":
                new_status, fatal_error = self.change_gen2_switch(turn_on)
            elif config_settings["ShellySmartSwitch"]["Model"] == "Shelly1PMG3":
                new_status, fatal_error = self.change_gen2_switch(turn_on)
            else:
                report_fatal_error(f"Unsupported Shelly switch model: {config_settings['ShellySmartSwitch']['Model']}")

            if new_status is None:
                #Log the failure
                logger_function(f"Shelly switch at {self.ip_address} reported error {fatal_error} when changing state. Attempt {attempt + 1} of {self.RETRY_COUNT}.", "error")
                time.sleep(self.RETRY_DELAY)
            else:
                return new_status

        # If we get here, we have failed to get the status after 3 attempts. Terminate
        report_fatal_error(fatal_error)

    def change_gen1_em_switch(self, turn_on: bool):
        """ Turn a Gen1 EM switch on or off
        :param turn_on: True to turn on the switch, False to turn it off. """

        fatal_error = None
        logger_function(f"Starting the Shelly energy meter change state function for {self.switch_id} at {self.ip_address}. switch on: {turn_on}", "debug")

        if turn_on:
            url = f"http://{self.ip_address}/relay/0?turn=on"
        else:
            url = f"http://{self.ip_address}/relay/0?turn=off"
        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = response = requests.get(url, headers=headers, timeout=config_settings["ShellySmartSwitch"]["Timeout"])
            response.raise_for_status()
            response_payload = response.json()
            new_status = response_payload["ison"]

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            fatal_error = f"Connection error changing Shelly energy meter relay: {e}"

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error = f"API timeout error changing Shelly energy meter relay: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error = f"Error changing Shelly energy meter relay: {e}"

        except KeyError as e:
            fatal_error = f"Key error in response payload from Shelly energy meter relay: {e}"

        if fatal_error is not None:
            return None, fatal_error

        if new_status != turn_on:
            report_fatal_error(f"The new state of the Shelly energy meter relay was not as expected. Expected: {turn_on}, Actual: {new_status}")

        new_status_str = "on" if new_status else "off"
        logger_function(f"Shelly energy meter relay at {self.ip_address} is {new_status_str}", "summary")
        return turn_on, None

    def change_gen2_switch(self, turn_on: bool):
        """ Turn a Gen2/3 switch on or off
        :param turn_on: True to turn on the switch, False to turn it off.
        :return: True if the switch was successfully turned on or off, False otherwise.
        """

        fatal_error = None
        logger_function(f"Starting the Shelly switch change state function for {self.switch_id} at {self.ip_address}. switch on: {turn_on}", "debug")

        url = f"http://{self.ip_address}/rpc"
        headers = {
            "Content-Type": "application/json"
        }

        payload = {
            "id": 0,
            "method": "switch.Set",
            "params": {
                "id": self.switch_id,
                "on": turn_on
            }
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=config_settings["ShellySmartSwitch"]["Timeout"])
            response_payload = response.json()
            prior_status = response_payload["result"]["was_on"]

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            fatal_error =  f"Connection error changing Shelly switch state: {e}"

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            fatal_error =  f"API timeout error changing Shelly switch state: {e}"

        except requests.exceptions.RequestException as e:
            fatal_error =  f"Error changing Shelly switch state: {e}"

        except KeyError as e:
            fatal_error =  f"Key error in response payload from Shelly switch: {e}"

        if fatal_error is not None:
            return None, fatal_error

        prior_status_str = "on" if prior_status  else "off"
        current_status_str = "on" if turn_on else "off"
        if prior_status != turn_on:
            logger_function(f"Changing Shelly switch {self.switch_id} at {self.ip_address} was {prior_status_str} and is now {current_status_str}", "summary")
        else:
            logger_function(f"Shelly switch {self.switch_id} at {self.ip_address} remains {current_status_str}", "summary")
        return turn_on, None
