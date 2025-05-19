'''
PowerController.py

Version: 10

Goal: To run a high energy device pool pump (or any smart switch controlled device) based on
electricity prices from the Amber API.
'''
import json
import os
import csv
import sys
import math
import random
import inspect
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
from utility import ConfigManager, ShellySwitch, merge_configs, send_email
from utility import register_logger, register_configurator, register_scheduler_state, report_fatal_error, fatal_error_tracking

CONFIG_FILE = "PowerControllerConfig.yaml"
GENERAL_API_TIMEOUT = 10
RANDOMISE_DURATIONS = False
GENERATE_ENERGY_DATA = False

# Setup the active configuration
SystemConfiguration = ConfigManager()
config = SystemConfiguration.get_config()


def write_log_message(message: str, verbosity: str):
    """Writes a log message to the console and/or a file based on verbosity settings."""
    config_file_setting_str = config["Files"]["LogFileVerbosity"]
    console_setting_str = config["Files"]["ConsoleVerbosity"]

    if verbosity not in ["error", "warning", "summary", "detailed", "debug"]:
        print("Invalid verbosity setting passed to write_log_message(). Must be 'summary' or 'detailed'.", file=sys.stderr)
        sys.exit(1)

    switcher = {
        "none": 0,
        "error": 1,
        "warning": 2,
        "summary": 3,
        "detailed": 4,
        "debug": 5
    }

    config_file_setting = switcher.get(config_file_setting_str, 0)
    console_setting = switcher.get(console_setting_str, 0)
    message_level = switcher.get(verbosity, 0)

    # Deal with console message first
    if console_setting >= message_level and console_setting > 0:
        if verbosity == "error":
            print("ERROR: " + message, file=sys.stderr)
        elif verbosity == "warning":
            print("WARNING: " + message)
        else:
            print(message)

    # Now write to the log file if needed
    if config["Files"]["MonitoringLogFile"] is not None:
        file_path = SystemConfiguration.select_file_location(config["Files"]["MonitoringLogFile"])
        error_str = " ERROR" if verbosity == "error" else " WARNING" if verbosity == "warning" else ""
        if config_file_setting >= message_level and config_file_setting > 0:
            with open(file_path, "a", encoding="utf-8") as file:
                if message == "":
                    file.write("\n")
                else:
                    file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{error_str}: {message}\n")

def initialise_monitoring_logfile():
    """Initialise the monitoring log file. If it exists, truncate it to the max number of lines."""
    if config["Files"]["MonitoringLogFile"] is None:
        return

    file_path = SystemConfiguration.select_file_location(config["Files"]["MonitoringLogFile"])

    if os.path.exists(file_path):
        # Monitoring log file exists - truncate excess lines if needed.
        with open(file_path, 'r', encoding='utf-8') as file:
            max_lines = config["Files"]["MonitoringLogFileMaxLines"]

            if max_lines > 0:
                lines = file.readlines()

                if len(lines) > max_lines:
                    # Keep the last max_lines rows
                    keep_lines = lines[-max_lines:] if len(lines) > max_lines else lines


                    # Overwrite the file with only the last 1000 lines
                    with open(file_path, 'w', encoding="utf-8") as file:
                        file.writelines(keep_lines)


class PowerSchedulerState:
    """Class to manage the state of the power device scheduler."""
    def __init__(self):

        register_scheduler_state(self)        # Register the scheduler state

        # Create a default state dictionary
        self.default_state = {
            "MaxDailyRuntimeAllowed": config["DeviceRunScheule"]["MaximumRunHoursPerDay"],
            "LastStateSaveTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "TotalRuntimePriorDays": None,
            "AverageRuntimePriorDays": None,
            "CurrentShortfall": None,
            "ForecastRuntimeToday": None,
            "IsDeviceRunning": None,
            "DeviceLastStartTime": None,
            "DeviceType": config["DeviceType"]["Type"],
            "DeviceName": config["DeviceType"]["Label"],
            "LastStatusMessage": None,
            "CurrentPrice": None,
            "PriceTime": None,
            "EnergyAtLastStart": None,
            "EnergyUsed": 0,
            "TotalCost": 0,
            "AveragePrice": None,
            "EarlierTotals": {
                "EnergyUsed": 10000 if GENERATE_ENERGY_DATA else 0,
                "TotalCost": 203 if GENERATE_ENERGY_DATA else 0,
                "RunTime": 0
            },
            "AlltimeTotals": {
                "EnergyUsed": 0,
                "TotalCost": 0,
                "AveragePrice": None,
                "RunTime": 0
                },
            "TodayRunPlan": [],
            "TodayOriginalRunPlan": [],
            "AverageForecastPrice": None,
            "DailyData": []
        }

        # Now populate some defaults for the DailyData[] dictionary
        for i in range(8):
            date_today = datetime.today() + timedelta(days=-i)  # Offset the date by i days

            daily_data = {
                "ID": i,
                "Date": date_today.strftime("%Y-%m-%d"),  # Format the date as a string
                "RequiredDailyRuntime": SystemConfiguration.get_target_hours(date_today),
                "PriorShortfall": 0,
                "TargetRuntime": None,
                "RuntimeToday": None,
                "RemainingRuntimeToday": None,
                "EnergyUsed": 0,
                "AveragePrice": None,
                "TotalCost": 0,
                "DeviceRuns": []  # Initialize as an empty list
            }

            self.default_state["DailyData"].append(daily_data)  # Add the dictionary to the list

            # Now add some defaults for the DeviceRuns[] array for prior days
            if i > 0:
                if RANDOMISE_DURATIONS:
                    num_runs = random.randint(2, 8)
                else:
                    num_runs = 1
                start_time = datetime.strptime(daily_data["Date"], "%Y-%m-%d")
                if RANDOMISE_DURATIONS:
                    start_time += timedelta(hours=random.randint(0, 5), minutes=random.randint(0, 40))

                # Make each run last for a num_runs fraction of the target hours for that day less a random shortfall
                run_duration = SystemConfiguration.get_target_hours(date_today) / num_runs
                if RANDOMISE_DURATIONS:
                    watts_per_hour = random.randint(1000, 2000)
                else:
                    watts_per_hour = 1000

                for j in range(num_runs):
                    if j == num_runs - 1:
                        if RANDOMISE_DURATIONS:
                            run_duration -= random.randint(0, 10) / 60  # Last run is shorter by a random amount
                        if run_duration <= 0:
                            run_duration = 5 / 60
                    if RANDOMISE_DURATIONS:
                        price = round(random.uniform(15.00, 25.00), 2)
                    else:
                        price = 20.00
                    run_data = {
                        "ID": j,
                        "StartTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "EndTime": (start_time + timedelta(hours=run_duration)).strftime("%Y-%m-%d %H:%M:%S"),
                        "RunTime": run_duration,
                        "EnergyUsedStart": None,
                        "EnergyUsedForRun": (watts_per_hour * run_duration) if GENERATE_ENERGY_DATA else 0,
                        "Price": price,
                        "Cost": (watts_per_hour * run_duration * price / 1000) if GENERATE_ENERGY_DATA else 0,
                    }
                    daily_data["DeviceRuns"].append(run_data)

                    start_time += timedelta(hours=run_duration + random.randint(0, 10) / 60)  # Increment the start time for the next run

        # Now load the latest state from file
        self.load_state()

        # Reset some of the daily data values from current configuration
        for day in self.state["DailyData"]:
            self.set_daily_data(day["ID"], day_data=day)

        # Override values set in config file
        self.state["MaxDailyRuntimeAllowed"] = config["DeviceRunScheule"]["MaximumRunHoursPerDay"]
        self.state["DeviceType"] = config["DeviceType"]["Type"]
        self.state["DeviceName"] = config["DeviceType"]["Label"]
        self.state["LastStatusMessage"] = None

        # See if we need to skip today
        self.skip_run_today = False
        if SystemConfiguration.is_no_run_today():
            write_log_message(f"{self.state['DeviceName']} is not scheduled to run today.", "summary")
            self.skip_run_today = True

    def load_state(self):
        """ Load the current state from the JSON file   """

        file_path = SystemConfiguration.select_file_location(config["Files"]["SavedStateFile"])
        if os.path.exists(file_path):

            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    file_state = json.load(file)
                    self.state = merge_configs(self.default_state, file_state)
                    write_log_message(f"Successfully loaded state from {file_path}.", "debug")
            except json.JSONDecodeError as e:
                report_fatal_error(f"Error decoding JSON from {file_path}: {e}")

        else:
            self.state = self.default_state

    def save_state(self):
        """ Save state to file  """

        file_path = SystemConfiguration.select_file_location(config["Files"]["SavedStateFile"])
        write_log_message(f"PowerSchedulerState.save_state() Saving state to {file_path}", "debug")
        self.state["LastStateSaveTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(self.state, file, indent=4)

        # Now if the WebsiteBaseURL hasbeen set, save the state to the web server
        if config["DeviceType"]["WebsiteBaseURL"] is not None:
            api_url = config['DeviceType']['WebsiteBaseURL'] + "/api/submit"
            
            if config['DeviceType']['WebsiteAccessKey'] is not None:
                access_key= config['DeviceType']['WebsiteAccessKey']
                api_url += f"?key={access_key}"  # Add access_key as a query parameter

            headers = {
                "Content-Type": "application/json"
            }
            json_object = self.state

            try:
                response = requests.post(api_url, headers=headers, json=json_object, timeout=GENERAL_API_TIMEOUT)
                response.raise_for_status()
                write_log_message(f"Posted PowerSchedulerState to {api_url}", "debug")
            except requests.exceptions.HTTPError as e:
                if response.status_code == 403:  # Handle 403 Forbidden error
                    write_log_message(f"Access denied (403 Forbidden) when posting to {api_url}. Check your access key or permissions.", "error")
                else:
                    write_log_message(f"HTTP error saving state to web server at {api_url}: {e}", "warning")
            except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
                write_log_message(f"Web server at {api_url} is unavailable. Error was: {e}", "warning")
            except requests.exceptions.RequestException as e:
                report_fatal_error(f"Error saving state to web server at {api_url}: {e}")

    def get_daily_data(self, day_number):
        """ Returns a dict of the data for the specified day (offset days prior to today)
         If it doesn't exist, returns None """

        if 0 <= day_number < len(self.state["DailyData"]):  # Check if day_number is a valid index
            return self.state["DailyData"][day_number]
        else:
            return None

    def set_daily_data(self, day_number, day_data = None):
        """ Store the dict of the data for the specified day (offset days prior to today) """

        if day_number < 0 or day_number > 7:
            report_fatal_error(f"Invalid day_number of {day_number} passed.")

        # Set the DailyData element using the passed dict. If that's none, set to default values.
        date_today = datetime.today() + timedelta(days=-day_number)  # Offset the date by i days
        if day_data is None:

            today_data = {
                "ID": day_number,
                "Date": date_today.strftime("%Y-%m-%d"),  # Format the date as a string
                "RequiredDailyRuntime": SystemConfiguration.get_target_hours(date_today),
                "PriorShortfall": 0,
                "TargetRuntime": None,
                "RuntimeToday": 0,
                "RemainingRuntimeToday": None,
                "EnergyUsed": 0,
                "AveragePrice": None,
                "TotalCost": 0,
                "DeviceRuns": []  # Initialize as an empty list
            }
            self.state["DailyData"][day_number] = today_data
        else:
            self.state["DailyData"][day_number] = day_data

            # Make sure the ID is correct
            self.state["DailyData"][day_number]["ID"] = day_number

            # make sure the RequiredDailyRuntime is correct
            self.state["DailyData"][day_number]["RequiredDailyRuntime"] = SystemConfiguration.get_target_hours(date_today)

        return True

    def consolidate_device_run_data(self, device_state):
        """ Close off any open device runs for today and merge any concurrent DeviceRuns[] elements
        device_state is the current state of the switch - a ShellySwitchState object """

        # Make sure we close off the last DeviceRuns[] entry for each day
        did_close_run = False
        for day in self.state["DailyData"]:
            if len(day["DeviceRuns"]) > 0:
                last_run = day["DeviceRuns"][-1]

                if last_run["EndTime"] is None: # We have a run that hasn't been closed off yet
                    # If it's a prior day and it wasn't closed off on that day, set end time and duration to 1 sec before midnight
                    did_close_run = True
                    if day["Date"] != datetime.today().strftime("%Y-%m-%d"):
                        end_time = datetime.strptime(day["Date"], "%Y-%m-%d") + timedelta(days=1, hours=0, minutes=0, seconds=-1)
                    else:
                        end_time = datetime.now()
                    last_run["EndTime"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
                    last_run["RunTime"] = round((end_time - datetime.strptime(last_run["StartTime"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600, 4)

                    # Calaculate energy used for this run since it started if our switch is currently available
                    # Note that price was set in log_device_state()
                    if device_state is None:
                        last_run["EnergyUsedForRun"] = 0
                    else:
                        last_run["EnergyUsedForRun"] = device_state["EnergyUsed"] - last_run["EnergyUsedStart"]
                        last_run["Cost"] = (last_run["EnergyUsedForRun"] or 0) * (last_run["Price"] or 0) / 1000
                    write_log_message(f"Updated DailyData[{day['ID']}].DeviceRuns[{last_run['ID']}] with end time {last_run['EndTime']}.", "debug")

        # Loop through all the DeviceRuns[] except the last one and see if we need to recalculate the energy used
        todays_data = self.state["DailyData"][0]["DeviceRuns"]
        if len(todays_data) > 1:
            for run_num in range(0, len(todays_data)-1):
                this_run = todays_data[run_num]
                next_run = todays_data[run_num + 1]

                if this_run["EnergyUsedForRun"] == 0:
                    this_run["EnergyUsedForRun"] = next_run["EnergyUsedStart"] - this_run["EnergyUsedStart"]
                    this_run["Cost"] = (this_run["EnergyUsedForRun"] or 0) * (this_run["Price"] or 0) / 1000

        #Aggregate the DeviceRuns[] data each day including today
        for day in self.state["DailyData"]:
            consolidated_device_runs = []
            new_device_run = None
            new_device_run_idx = 0
            for this_run in day["DeviceRuns"]:
                # If we don't have a run in play, or the start time of this run 1 min after the end time of
                # the last run, then create a new consolidated element
                start_time = datetime.strptime(this_run["StartTime"], "%Y-%m-%d %H:%M:%S")
                if new_device_run is not None:
                    end_time = datetime.strptime(new_device_run["EndTime"], "%Y-%m-%d %H:%M:%S")
                else:
                    end_time = None
                if new_device_run is None or (start_time - end_time).total_seconds() > 60:

                    # Create a new consolidated run object that we will add to the array
                    new_device_run = {
                        "ID": new_device_run_idx,
                        "StartTime": this_run["StartTime"],
                        "EndTime": this_run["EndTime"],
                        "RunTime": this_run["RunTime"],
                        "EnergyUsedStart": this_run["EnergyUsedStart"],
                        "EnergyUsedForRun": this_run["EnergyUsedForRun"],
                        "Price": this_run["Price"],
                        "Cost": this_run["Cost"],
                    }
                    # Add this new run to the consolidated list
                    consolidated_device_runs.append(new_device_run)
                    new_device_run_idx += 1
                else:
                    # Extend the existing consolidated run object - the new_device_run object previously added to the consolidated array
                    consolidated_device_runs[new_device_run_idx - 1]["EndTime"] = this_run["EndTime"]
                    consolidated_device_runs[new_device_run_idx - 1]["RunTime"] += this_run["RunTime"]
                    consolidated_device_runs[new_device_run_idx - 1]["EnergyUsedForRun"] += this_run["EnergyUsedForRun"]
                    consolidated_device_runs[new_device_run_idx - 1]["Cost"] += (this_run["Cost"] or 0)
                    if consolidated_device_runs[new_device_run_idx - 1]["Cost"] > 0 and consolidated_device_runs[new_device_run_idx - 1]["EnergyUsedForRun"] > 0:
                        consolidated_device_runs[new_device_run_idx - 1]["Price"] = round(consolidated_device_runs[new_device_run_idx - 1]["Cost"] / (consolidated_device_runs[new_device_run_idx - 1]["EnergyUsedForRun"] / 1000), 2)
                    else:
                        consolidated_device_runs[new_device_run_idx - 1]["Price"] = None

            # Got through the list of original runs. Replaced DeviceRuns entry
            day["DeviceRuns"].clear()
            day["DeviceRuns"] = consolidated_device_runs

        # Return True if there was an open device
        return did_close_run

    def is_device_run_open(self):
        """ Check if there are any open device runs """
        data_today = self.state["DailyData"][0]
        device_open = False

        if len(data_today["DeviceRuns"]) > 0:
            last_run = data_today["DeviceRuns"][-1]
            if last_run["EndTime"] is None:
                device_open = True

        return device_open

    def calculate_running_totals(self):
        """ Confirm that no day rollover is needed """

        if self.state["DailyData"][0]["Date"] != datetime.today().strftime("%Y-%m-%d"):
            report_fatal_error("called when DailyData[0] was not today")

        # Current date and time
        now = datetime.now()

        # Loop through each day starting with the oldest through to today and recalculate all the aggregate values
        # Reset the global aggregate numbers
        self.state["TotalRuntimePriorDays"] = 0
        self.state["AverageRuntimePriorDays"] = 0
        self.state["EnergyUsed"] = 0
        self.state["TotalCost"] = 0
        self.state["AveragePrice"] = None
        running_shortfall = 0   # Running shortfall from the prior day

        # Update the global aggregate numbers for the prior 7 days
        for day_data in reversed(self.state["DailyData"]):
            # Set PriorShortfall for today to be the running total
            day_data["PriorShortfall"] = running_shortfall

            # Reset the running totals for today
            day_data["RuntimeToday"] = 0
            day_data["EnergyUsed"] = 0
            day_data["TotalCost"] = 0

            # Update today's values from the DeviceRuns array for today
            if len(day_data["DeviceRuns"]) > 0:
                # We have some device run data - calculate the running totals for today
                for run in day_data["DeviceRuns"]:
                    # Add this device run to the running totals as long as it's not currently open
                    if run["EndTime"] is not None:
                        day_data["RuntimeToday"] += run["RunTime"]
                        day_data["EnergyUsed"] += run["EnergyUsedForRun"]
                        day_data["TotalCost"] += (run["Cost"] or 0)

            # And now the average price for today
            if (day_data["EnergyUsed"] or 0) > 0:
                day_data["AveragePrice"] = day_data["TotalCost"] / (day_data["EnergyUsed"] / 1000)

            # Calculate the TargetRuntime for today. For pool pumps this should be
            #   RequiredDailyRuntime + PriorShortfall and must be at least MinimumRunHoursPerDay and at most MaximumRunHoursPerDay
            # For hot water systems this should be RequiredDailyRuntime. we calculate the shortfall but don't carry it forward
            if self.skip_run_today:
                # We're scheduled to skip today, so set the target runtime to 0
                day_data["TargetRuntime"] = 0
            elif config["DeviceType"]["Type"] == "HotWaterSystem":
                day_data["TargetRuntime"] = day_data["RequiredDailyRuntime"]
            else:
                day_data["TargetRuntime"] = day_data["RequiredDailyRuntime"] + day_data["PriorShortfall"]
                if day_data["TargetRuntime"] < config["DeviceRunScheule"]["MinimumRunHoursPerDay"]:
                    day_data["TargetRuntime"] = config["DeviceRunScheule"]["MinimumRunHoursPerDay"]
                if day_data["TargetRuntime"] > config["DeviceRunScheule"]["MaximumRunHoursPerDay"]:
                    day_data["TargetRuntime"] = config["DeviceRunScheule"]["MaximumRunHoursPerDay"]

            # Calculate running_shortfall to be used for the next day
            if config["DeviceType"]["Type"] == "PoolPump":
                running_shortfall += day_data["RequiredDailyRuntime"] - day_data["RuntimeToday"]

            # And the global running totals
            if day_data["ID"] > 0:
                self.state["TotalRuntimePriorDays"] += day_data["RuntimeToday"]or 0
            self.state["EnergyUsed"] += day_data["EnergyUsed"] or 0
            self.state["TotalCost"] += day_data["TotalCost"] or 0

        # Finally the remaining aggregate values
        self.state["AverageRuntimePriorDays"] = self.state["TotalRuntimePriorDays"] / 7
        if self.state["EnergyUsed"] > 0:
            self.state["AveragePrice"] = self.state["TotalCost"] / (self.state["EnergyUsed"] / 1000)
        self.state["CurrentShortfall"] = max(0,running_shortfall)
        self.state["AlltimeTotals"]["EnergyUsed"] = self.state["EnergyUsed"] + self.state["EarlierTotals"]["EnergyUsed"]
        self.state["AlltimeTotals"]["TotalCost"] = self.state["TotalCost"] + self.state["EarlierTotals"]["TotalCost"]
        if self.state["AlltimeTotals"]["EnergyUsed"] > 0:
            self.state["AlltimeTotals"]["AveragePrice"] = self.state["AlltimeTotals"]["TotalCost"] / (self.state["AlltimeTotals"]["EnergyUsed"] / 1000)
        self.state["AlltimeTotals"]["RunTime"] = self.state["TotalRuntimePriorDays"] + self.state["DailyData"][0]["RuntimeToday"] + self.state["EarlierTotals"]["RunTime"]


        # Values already set above:
        # TargetRuntime = How many hours we need to run today in total. Defaults to CurrentShortFall but capped by max / min hours per day
        # RuntimeToday = How many hours have we run so far today
        # CurrentShortfall = Shortfall for today which takes into account hours run so far today and RequiredDailyRuntime

        # So now we can calculate RemainingRuntimeToday = How many hours do we have left to run (TargetRuntime - RuntimeToday)

        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        # How many hours left before midnight
        hours_left_today = math.floor((midnight - now).total_seconds() / 60) / 60

        # How long have we been running for today so far
        runtime_today = self.state["DailyData"][0]["RuntimeToday"]
        target_total_runtime = self.state["DailyData"][0]["TargetRuntime"]

        # Set RemainingRuntimeToday such that:
        # - Defaults to TargetRuntime - RuntimeToday
        # - If less than 0, set to 0
        # - If runtime_today < MinimumRunHoursPerDay, set to MinimumRunHoursPerDay - runtime_today
        # - If greater than  hours_left_today, cap at that

        remaining_runtime = target_total_runtime - runtime_today
        remaining_runtime = max(remaining_runtime, 0)
        remaining_runtime = min(remaining_runtime, hours_left_today)

        self.state["DailyData"][0]["RemainingRuntimeToday"] = remaining_runtime

    def check_day_rollover(self):
        """ Check if a new day has started and update history accordingly. """

        current_date = datetime.now().strftime("%Y-%m-%d")
        daily_data = self.get_daily_data(0)     # Get the daily data for today if any
        if daily_data is None:
            # We have no daily data for today, nothing to do yet
            return False
        else:
            # See if date for 0 element is prior to today
            if daily_data["Date"] == current_date:
                return False

            write_log_message("PowerSchedulerState.check_day_rollover(): New day detected, rolling data over to prior days.", "debug")

            #First increment the EarlierTotals for the oldest date that we're loosing
            self.state["EarlierTotals"]["EnergyUsed"] += self.state["DailyData"][7]["EnergyUsed"]
            self.state["EarlierTotals"]["TotalCost"] += self.state["DailyData"][7]["TotalCost"]
            self.state["EarlierTotals"]["RunTime"] += self.state["DailyData"][7]["RuntimeToday"]

            for i in range(7, 0, -1):
                daily_data = self.get_daily_data(i - 1)
                self.set_daily_data(i, daily_data)

            # Now initialise data for today
            self.set_daily_data(0)

            # Check the energy use for the prior day
            self.check_yesterday_energy_usage()

            return True

    def check_yesterday_energy_usage(self):
        """ Check if the energy used yesterday was more than expected. """

        # Get the daily data for yesterday
        yesterday_data = self.get_daily_data(1)
        if yesterday_data is None:
            write_log_message("PowerSchedulerState.check_yesterday_energy_usage(): No data for yesterday.", "warning")
            return

        # Check if the energy used was less than expected
        threashold = config["Email"]["DailyEnergyUseThreshold"] or 0
        if threashold > 0:
            if yesterday_data["EnergyUsed"] > threashold:
                warning_msg = f"{self.state['DeviceName']} energy used on {yesterday_data['Date']} was {yesterday_data['EnergyUsed']:.0f} watts, which exceeded the expected limit of {threashold}."
                write_log_message(warning_msg, "warning")

                # Send an email notification if configured
                send_email("Energy Usage Alert", warning_msg)

    def set_current_price(self, price):
        """Sets the current price in the state dictionary."""

        self.state["CurrentPrice"] = price
        self.state["PriceTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:00")

    def __getitem__(self, index):
        """Allows access to the state dictionary using square brackets."""
        return self.state.get(index)

    def __setitem__(self, index, value):
        """Allows setting values in the state dictionary using square brackets."""
        self.state[index] = value


class PriceData:
    """Class to manage the Amber price data for the device scheduler."""
    def __init__(self):
        """ Initialise the PriceData class. Gets the Amber price data and builds
        the array of prices. """

        # Get the Amber site ID.
        self.site_id = self.get_site_id()

        # To Do - build the enriched array of prices, up to midnight
        amber_prices = self.get_prices()

        # Build the enriched price data array and truncate to only prices for today
        self.prices = self.process_amber_prices(amber_prices)

        # And the sorted version
        self.prices_sorted = self.prices.copy()
        self.prices_sorted.sort(key=lambda x: x["Price"])

    def get_site_id(self):
        """Fetches the site ID from the Amber API. """

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {config['AmberAPI']['APIKey']}"
        }
        try:
            url = config['AmberAPI']['BaseUrl'] + "/sites"
            write_log_message(f"Getting Amber site ID using API call: {url}", "debug")

            response = requests.get(f"{url}", headers=headers, timeout=config["AmberAPI"]["Timeout"])
            response.raise_for_status()
            sites = response.json()
            for site in sites:
                if site.get("status") == "active":
                    return site.get("id")
            write_log_message("No active sites found.", "error")
            return None
        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            report_fatal_error(f"Connection error fetching Amber site ID at {url}: {e}")

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            report_fatal_error(f"API timeout error fetching Amber site ID at {url}: {e}")

        except requests.exceptions.RequestException as e:
            report_fatal_error(f"Error fetching Amber site ID: {e}")

        return None

    def get_prices(self):
        """Fetches the price forecast and saves the full JSON response."""

        if not self.site_id:
            write_log_message("No site Amber ID available. Cannot fetch prices.", "error")
            return None

        write_log_message("Downloading Amber prices for next 24 hours.", "summary")

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {config['AmberAPI']['APIKey']}"
        }
        url = f"{config['AmberAPI']['BaseUrl']}/sites/{self.site_id}/prices/current?next=47&previous=0&resolution=30"

        write_log_message(f"Getting Amber prices using API call: {url}", "debug")

        try:
            response = requests.get(url, headers=headers, timeout=config["AmberAPI"]["Timeout"])
            response.raise_for_status()
            price_data = response.json()

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            report_fatal_error(f"Connection error fetching Amber prices at {url}: {e}")

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            report_fatal_error(f"API timeout error fetching Amber prices at {url}: {e}")

        except requests.exceptions.RequestException as e:
            report_fatal_error(f"Error fetching Amber prices: {e}")

        # Add local time entries to the returned dict
        enhanced_data = []
        for entry in price_data:
            new_entry = OrderedDict()
            for key, value in entry.items():
                new_entry[key] = value
                if key == "startTime":
                    new_entry["localStartTime"] = self.convert_utc_dt_string(entry["startTime"])
                if key == "endTime":
                    new_entry["localEndTime"] = self.convert_utc_dt_string(entry["endTime"])

            enhanced_data.append(new_entry)

        if config["Files"]["LatestPriceData"] is not None:
            lastest_price_data_path = SystemConfiguration.select_file_location(config["Files"]["LatestPriceData"])
            write_log_message(f"Saving latest price data to {lastest_price_data_path}", "detailed")

            with open(lastest_price_data_path, "w", encoding="utf-8") as json_file:
                json.dump(enhanced_data, json_file, indent=4)

        return enhanced_data

    def process_amber_prices(self, amber_prices):
        """Processes the enriched Amber price dictionary and build our custom dictionary
        for prices in the required channel through to midnight ."""

        return_prices = []
        slot = 0
        for amber_entry in amber_prices:
            # If we've moved into the next day, break
            entry_start_time = datetime.strptime(amber_entry["localStartTime"], "%Y-%m-%dT%H:%M:%S")
            # If the entry if for today
            if entry_start_time.date() == datetime.today().date():
                # If this entry is the required channel, add it to the list
                if amber_entry.get("channelType") == config["AmberAPI"]["Channel"]:
                    price_entry = {
                        "Slot": slot,
                        "StartTime": amber_entry["localStartTime"].replace("T", " "),
                        "EndTime": amber_entry["localEndTime"].replace("T", " "),
                        "Price": amber_entry["perKwh"],
                        "Channel": amber_entry["channelType"],
                        "Selected": None,
                    }

                    return_prices.append(price_entry)
                    slot += 1

        if len(return_prices) == 0:
            report_fatal_error(f"No Amber prices found for the {config['AmberAPI']['Channel']} channel.")

        write_log_message(f"{len(return_prices)} prices fetched successfully.", "debug")

        return return_prices

    def get_current_price(self):
        """Fetches the current price from the Amber API."""

        return self.prices[0]["Price"]

    def get_worst_price(self):
        """Fetches the worst price from the Amber API."""

        return self.prices_sorted[-1]["Price"]

    def convert_utc_dt_string(self, utc_time_str: str) -> str:
        """Converts a UTC datetime string to a local datetime string."""

        # Parse the string into a datetime object (with UTC timezone)
        utc_dt = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).replace(tzinfo=None)

        # ZoneInfo() fails for my AEST timezone, so instead calculate the current time difference for UTC and local time
        local_timenow = datetime.now().replace(tzinfo=None)
        utc_timenow = datetime.now(timezone.utc).replace(tzinfo=None)

        tz_diff = local_timenow - utc_timenow + timedelta(0,1)

        # Convert to local time
        local_dt = utc_dt + tz_diff
        local_dt = local_dt.replace(microsecond=0)

        return local_dt.isoformat()

class PowerScheduler:
    """Class to manage the device scheduling based on electricity prices."""
    def __init__(self):
        """ Initialise the PowerScheduler class. """

        initialise_monitoring_logfile()

        # Create an instance of the PowerScheduleState dictionary and load the prior state from file
        self.state = PowerSchedulerState()
        self.switch = None

        # Log a warning it it's been more than 30 mins since the last state save
        last_state_save_time = self.state["LastStateSaveTime"]
        if last_state_save_time is not None:
            last_state_save_time = datetime.strptime(last_state_save_time, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            time_diff = now - last_state_save_time
            if time_diff.total_seconds() > 1800:
                write_log_message(f"{self.state['DeviceName']} last run time was {time_diff.total_seconds() / 3600:.1f} hours ago. This is too long - please run at least every 30 minutes.", "warning")

        # Create an instance of the PriceData class and get the latest prices for the remainder of today
        self.price_data = PriceData()

        # Save latest price
        current_price = self.price_data.get_current_price()
        self.state.set_current_price(current_price)

    def register_switch(self, shelly_switch):
        """ Register the Shelly switch with the scheduler."""
        self.switch = shelly_switch

    def get_current_slot(self):
        """Calculate the current 30-minute slot based on system time."""
        now = datetime.now()
        return (now.hour * 2) + (now.minute // 30)

    def should_device_run(self):
        """Determines if the device should run in the current slot."""

        # Calculate how many slots we need to run today
        required_slots, selected_slots = self.calculate_required_slots()

        run_device = False
        self.state["TodayRunPlan"].clear()

        if selected_slots > 0:
            run_device, reason_why_message, override_message = self.evaluate_run_conditions()

            self.record_run_plan(run_device, selected_slots, reason_why_message, override_message)
        else:
            if self.state.skip_run_today:
            # If we're scheduled to skip today, then we don't run the device
                status_message = f"{self.state['DeviceName']} is scheduled to not run today."
            elif required_slots > 0:
                status_message = f"All remaining time slots for today are too expensive. {self.state['DeviceName']} will not run."
            else:
                status_message = f"No runtime needed - {self.state['DeviceName']} will not run."

            # Save the status message
            self.state["LastStatusMessage"] = status_message
            write_log_message(status_message, "summary")

            # Write the run log to file if needed
            if not self.switch.switch_online:
                run_device = None
            self.write_csv_runlog(selected_slots, self.price_data.prices[0]['Price'], self.state["AverageForecastPrice"], run_device)

        # Save the run plan to the file
        self.state.save_state()
        return run_device

    def calculate_required_slots(self):
        """Calculate the required slots and identify the cheapest slots. Returns the number of slots 
        that we need and the number of slots that we have actually selected."""

        available_slots = len(self.price_data.prices)
        remaining_hours = self.state["DailyData"][0]["RemainingRuntimeToday"]
        required_slots = math.ceil(remaining_hours * 2)
        required_slots = min(required_slots, available_slots)  # Don't exceed available slots

        # Flag the slots in prices array that we need
        selected_slots = 0
        for idx in range(required_slots):
            # Only select the price if its less than the maximum price
            if self.price_data.prices_sorted[idx]["Price"] <= config["DeviceRunScheule"]["MaximumPriceToRun"]:
                self.price_data.prices_sorted[idx]["Selected"] = True
                slot = self.price_data.prices_sorted[idx]["Slot"]
                self.price_data.prices[slot]["Selected"] = True
                selected_slots += 1
            else:
                write_log_message(f"Price {self.price_data.prices_sorted[idx]['Price']:.1f} c/kWh for {self.price_data.prices_sorted[idx]['StartTime']} exceeds maximum price of {config['DeviceRunScheule']['MaximumPriceToRun']} c/kWh. We were only able to pick {selected_slots} of the {required_slots} required slots", "detailed")
                break

        # Make note of the maximum runtime left today based on selected slots
        self.state["ForecastRuntimeToday"] = selected_slots / 2

        return required_slots, selected_slots

    def flag_current_slot(self, is_selected):
        """Flag the Selected attribute in the curent price slot."""
        self.price_data.prices_sorted[0]["Selected"] = is_selected
        slot = self.price_data.prices_sorted[0]["Slot"]
        self.price_data.prices[slot]["Selected"] = is_selected

    def evaluate_run_conditions(self):
        """Evaluate the conditions to determine if the device should run."""

        worst_price = self.price_data.get_worst_price()
        current_price = self.price_data.get_current_price()
        reason_why_message = None
        override_message = None

        # If the switch us unable to run, then we can't run it
        if self.switch is not None and not self.switch.switch_online:
            # Here
            run_device = False
            reason_why_message = "smart switch is not available"
        else:
            # By default we don't run the device
            run_device = False
            reason_why_message = "current time slot not one of the cheapest forecast slots for the rest of today"

            # Run device if the current time slot appears in our list of cheapest slots
            if self.price_data.prices[0]["Selected"]:
                run_device = True
                reason_why_message = "current time slot is in the cheapest slots"

            # If we haven't run the device for the minimum number of hours today, and the current price is
            # less than the most expensice price in our chosen slots (raised by the threashold factor),
            # then run the device
            today_runtime = self.state["DailyData"][0]["RuntimeToday"]
            min_hours = config["DeviceRunScheule"]["MinimumRunHoursPerDay"]
            excess_threashold = config["DeviceRunScheule"]["ThresholdAboveCheapestPricesForMinumumHours"]
            if today_runtime < min_hours and current_price < worst_price * excess_threashold:
                run_device = True
                reason_why_message = (f"we haven't run the device for at least {min_hours} hours today and the"
                                        f" current price is less than the most expensive price in our chosen"
                                        f" slots plus {round((excess_threashold - 1), 2) * 100:.0f}%")

            if config["DeviceType"]["Type"] == "PoolPump":
                max_hours = config["DeviceRunScheule"]["MaximumRunHoursPerDay"]
                if today_runtime >= max_hours:
                    if run_device:
                        override_message = f"maximum daily runtime of {max_hours} hours reached."
                    run_device = False

        # Make sure the current price slot is properly flagged
        self.flag_current_slot(run_device)
        return run_device, reason_why_message, override_message

    def record_run_plan(self, run_device, selected_slots, reason_why_message, override_message):
        """Record the run plan for the device based on the calculated slots and conditions."""

        self.state["TodayRunPlan"].clear()

        # Make up a run plan for the time slots we are going to use
        i = 0
        average_forecast_price = 0
        start_time = None
        end_time = None
        concurrent_count = 1
        total_price = 0
        for price_idx, price in enumerate(self.price_data.prices):
            # price_idx is offset into prices[] array
            if price["Selected"]:
                # This is a price slot we are using
                end_time = datetime.strptime(price["EndTime"], "%Y-%m-%d %H:%M:%S")

                # If the prior slot was selected as well then it's concurrent
                if price_idx > 0 and self.price_data.prices[price_idx - 1]["Selected"]:
                    concurrent_count += 1
                    total_price += price["Price"]

                    # Update the existing entry
                    self.state["TodayRunPlan"][i-1]["To"] = end_time.strftime("%H:%M")
                    self.state["TodayRunPlan"][i-1]["AveragePrice"] = round(total_price / concurrent_count, 2)
                else:
                    # There's a gap since the last once, so add a new entry
                    total_price = price["Price"]
                    concurrent_count = 1
                    start_time = datetime.strptime(price["StartTime"], "%Y-%m-%d %H:%M:%S")
                    run_item = {
                        "ID": i,
                        "From": start_time.strftime("%H:%M"),
                        "To": end_time.strftime("%H:%M"),
                        "AveragePrice": round(total_price / concurrent_count, 2)
                    }
                    self.state["TodayRunPlan"].append(run_item)     # Add this slot to the run plan
                    i += 1

                # Save average forecast price
                average_forecast_price += price["Price"]

        # Now report out the aggregrate run plan
        device_run_plan_msg = ""
        for run_item in self.state["TodayRunPlan"]:
            device_run_plan_msg += f"                     {run_item['ID'] + 1}: From {run_item['From']} to {run_item['To']} - {run_item['AveragePrice']:.2f} c/kWh\n"

        # Calculate the average forecast price for the run plan
        average_forecast_price = average_forecast_price / selected_slots
        self.state["AverageForecastPrice"] = average_forecast_price

        # If we haven't logged any runs today, save a copy of the run plan
        if len(self.state["DailyData"][0]["DeviceRuns"]) == 0:
            self.state["TodayOriginalRunPlan"] = self.state["TodayRunPlan"].copy()

        today_runtime = self.state["DailyData"][0]["RuntimeToday"]
        run_device_str = "on" if run_device else "off"
        final_message = f"{self.state['DeviceName']} switch is {run_device_str}. Target: {self.state['DailyData'][0]['TargetRuntime']:.2f} hours. Actual: {today_runtime:.2f} hours. Planned: {self.state['ForecastRuntimeToday']:.2f}. Price now: {self.price_data.prices[0]['Price']:.2f} c/kWh. Average forecast price: {average_forecast_price:.2f} c/kWh. "

        if override_message:
            final_message += f"Won't run because {override_message}. "
            self.state["LastStatusMessage"] = f"{self.state['DeviceName']} won't run because {override_message}"
        elif reason_why_message:
            if run_device:
                final_message += f"Will run because {reason_why_message}. "
                self.state["LastStatusMessage"] = f"{self.state['DeviceName']} will run because {reason_why_message}"
            else:
                final_message += f"Won't run because {reason_why_message}. "
                self.state["LastStatusMessage"] = f"{self.state['DeviceName']} won't run because {reason_why_message}"

        # Append the run plan 
        if device_run_plan_msg != "":
            final_message += f" {self.state['DeviceName']} run plan:\n{device_run_plan_msg}"

        write_log_message(final_message, "summary")
        if config["Email"]["SendSummary"]:
            subject = f"{self.state['DeviceName']} scheduler Summary for {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            send_email(subject, final_message)

        # Write the run log to file if needed
        if not self.switch.switch_online:
            device_state = None
        else:
            device_state = run_device
        self.write_csv_runlog(selected_slots, self.price_data.prices[0]['Price'], average_forecast_price, device_state)

    def write_csv_runlog(self, required_slots, amber_price, forecast_price, should_run):
        """Initialise the run log file. If it exists, truncate it to the max number of lines."""

        if config["Files"]["RunLogFile"] is None:
            write_log_message("No log file specified. Run log will not be saved.", "debug")
            return

        file_path = SystemConfiguration.select_file_location(config["Files"]["RunLogFile"])
        SwitchState = ""
        if should_run is None:
            SwitchState = "Unavailable"
        elif should_run:
            SwitchState = "On"
        elif not should_run:
            SwitchState = "Off"

        if os.path.exists(file_path):
            # CSV log file exists - truncate excess lines if needed
            with open(file_path, 'r', newline='', encoding='utf-8') as file:
                max_lines = config["Files"]["RunLogFileMaxLines"]

                if max_lines > 0:
                    reader = list(csv.reader(file))

                    # Ensure there are more than max_lines lines (including header)
                    if len(reader) > max_lines + 1:
                        write_log_message(f"Trimming excess lines from {file_path}.", "debug")
                        header = reader[0]  # Preserve header
                        data = reader[-max_lines:]  # Keep the last max_lines rows

                        # Rewrite the file with the trimmed content
                        with open(file_path, 'w', newline='', encoding='utf-8') as file:
                            writer = csv.writer(file)
                            writer.writerow(header)  # Write header back
                            writer.writerows(data)  # Write last max_lines rows
        else:
            # CSV log file doesn't exist - create one with the header.
            with open(file_path, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["CurrentTime", "RequiredSlots", "CurrentPrice", "AverageForecastPrice", "SwitchState" ])

                write_log_message(f"Created new run log file at {file_path}.", "detailed")


        # Finally, write the run log to file if needed
        with open(file_path, mode="a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), required_slots,  round(amber_price, 2), round(forecast_price, 2), SwitchState])

    def validate_device_state(self, device_state):
        """ Validate the device state object """

        if device_state is None:
            report_fatal_error("called with None value")

        if device_state["Enabled"] != self.state["IsDeviceRunning"]:
            write_log_message(f"{self.state['DeviceName']} switch has been changed externally since the PowerController last stated. Switch on: {device_state['Enabled']} but we last set the switch to {self.state['IsDeviceRunning']}", "warning")

        # Check to see how long the pool device has been running for
        if self.state["IsDeviceRunning"] and config["DeviceType"]["Type"] == "PoolPump":
            start_time = datetime.strptime(self.state["DeviceLastStartTime"], "%Y-%m-%d %H:%M:%S")
            max_hours = config["DeviceRunScheule"]["MaximumRunHoursPerDay"]
            running_hours = (datetime.now() - start_time).total_seconds() / 3600
            if running_hours > max_hours:
                write_log_message(f"{self.state['DeviceName']} appears to have been running for {running_hours:.1f} hours, more than maximum of {max_hours} hours. This should never happen. ", "error")

                # Reset the start time so that we don't get this error every time
                self.state["DeviceLastStartTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return False

        return True

    def log_device_state(self, old_device_state, new_device_state):
        """ Record the state change of the device switch """

        function_name = self.__class__.__name__ + "." + inspect.currentframe().f_code.co_name + "()"

        # old_device_state and new_device_state are instances of ShellySwitchState
        if old_device_state is None or new_device_state is None:
            write_log_message(f"Starting {function_name} - switch is currently offline - updating system status.", "debug")
            self.state["IsDeviceRunning"] = False
            self.state["DeviceLastStartTime"] = None
        else:
            # Should never be called if the device run is open
            if self.state.is_device_run_open():
                report_fatal_error("called with an open device run.")

            # Record the device being turned on or turned off
            write_log_message(f"Starting {function_name} - prior state: {old_device_state['SwitchStateStr']} new state: {new_device_state['SwitchStateStr']}.", "debug")

            # If the device is running, add a new run entry
            if new_device_state["Enabled"]:
                run_num = len(self.state["DailyData"][0]["DeviceRuns"])
                if not old_device_state["Enabled"]:
                    write_log_message(f"Turning the {self.state['DeviceName']} on, starting run {run_num + 1}.", "summary")

                run_item = {
                    "ID": len(self.state["DailyData"][0]["DeviceRuns"]),
                    "StartTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "EndTime": None,
                    "RunTime": None,
                    "EnergyUsedStart": new_device_state["EnergyUsed"],
                    "EnergyUsedForRun": None,
                    "Price": round(self.state["CurrentPrice"], 2),
                    "Cost": None
                }
                self.state["DailyData"][0]["DeviceRuns"].append(run_item)

                self.state["IsDeviceRunning"] = True
                if self.state["DeviceLastStartTime"] is None:
                    self.state["DeviceLastStartTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.state["EnergyAtLastStart"] = new_device_state["EnergyUsed"]
            else:
                run_num = len(self.state["DailyData"][0]["DeviceRuns"])
                if old_device_state["Enabled"]:
                    write_log_message(f"Turning the {self.state['DeviceName']} off, closing out run {run_num}.", "summary")

                self.state["IsDeviceRunning"] = False
                self.state["DeviceLastStartTime"] = None
        self.state.save_state()


if __name__ == "__main__":
    this_device_label = config["DeviceType"]["Label"]

    register_logger(write_log_message)        # Register the logger function
    register_configurator(SystemConfiguration)        # Register the config settings

    write_log_message("", "summary")
    write_log_message(f"{this_device_label} starting...", "summary")
    scheduler = None

    try:
        # Create an instance of the PowerScheduler which will include the PowerSchedulerState
        # and also download the latest Amber prices for the rest of the day
        scheduler = PowerScheduler()

        # Create an instance of the ShellySwitch class
        smart_switch = ShellySwitch()

        # Register the switch with the scheduler
        scheduler.register_switch(smart_switch)

        # Get the current state of the switch or None if it's not available
        current_switch_status = smart_switch.get_status()

        #Make sure the switch is in the correct state
        if current_switch_status is not None:
            if not scheduler.validate_device_state(current_switch_status):
                CRITICAL_ERROR = f"device appears to have been running for more than {config['DeviceRunScheule']['MaximumRunHoursPerDay']} hours. This should never happen. See log file for details."
                send_email("PowerController device was running for too long", CRITICAL_ERROR)

        # Close out any open device runs and update the state
        scheduler.state.consolidate_device_run_data(current_switch_status)

        # Check for roll over to prior day if required
        scheduler.state.check_day_rollover()

        # Refesh running totals
        scheduler.state.calculate_running_totals()

        # Save the state
        scheduler.state.save_state()

        # Check if we need to run the device
        should_device_run = scheduler.should_device_run()

        # Turn the switch on or off as needed
        smart_switch.change_switch(should_device_run)

        # Get the new state of the switch
        new_switch_status = smart_switch.get_status()

        # Record the switch state change and save state to file
        scheduler.log_device_state(current_switch_status, new_switch_status)

        # If the prior run fails, send email that this run worked OK
        if fatal_error_tracking("get"):
            write_log_message(f"{this_device_label} run was successful after a prior failure.", "summary")
            send_email(f"{this_device_label} recovery", "PowerController run was successful after a prior failure.")
            fatal_error_tracking("set")
        sys.exit(0)

    # Handle any other untrapped exception
    except Exception as e:
        main_fatal_error = f"PowerController terminated unexpectedly due to unexpected error: {e}"
        report_fatal_error(main_fatal_error, report_stack=True)
