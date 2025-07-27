"""Manage the state data for the power scheduler."""

import datetime as dt
import json
import math
import random
from typing import Any

import requests
from sc_utility import DateHelper, SCCommon, SCConfigManager, SCLogger

from helper import AmberHelper

HTTP_STATUS_FORBIDDEN = 403


class PowerSchedulerState:
    """Class to manage the state of the power device scheduler."""

    def __init__(self, config: SCConfigManager, logger: SCLogger):
        """Initialize the PowerSchedulerState class.

        Args:
            config (SCConfigManager): Configuration manager instance.
            logger (SCLogger): Logger instance for logging messages.
        """
        local_tz = dt.datetime.now().astimezone().tzinfo
        self.config = config
        self.logger = logger

        # Create an instance of the AmberHelper class
        self.helper = AmberHelper(config, logger)

        # Create a default state dictionary
        self.default_state = {
            "MaxDailyRuntimeAllowed": self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay"),
            "LastStateSaveTime": DateHelper.now_str(),
            "TotalRuntimePriorDays": None,
            "AverageRuntimePriorDays": None,
            "CurrentShortfall": None,
            "ForecastRuntimeToday": None,
            "IsDeviceRunning": None,
            "DeviceLastStartTime": None,
            "DeviceType": self.config.get("DeviceType", "Type"),
            "DeviceName": self.config.get("DeviceType", "Label"),
            "LastStatusMessage": None,
            "LivePrices": True,
            "CurrentPrice": None,
            "PriceTime": None,
            "EnergyAtLastStart": None,
            "EnergyUsed": 0,
            "TotalCost": 0,
            "AveragePrice": None,
            "EarlierTotals": {
                "EnergyUsed": 0,
                "TotalCost": 0,
                "RunTime": 0,
            },
            "AlltimeTotals": {
                "EnergyUsed": 0,
                "TotalCost": 0,
                "AveragePrice": None,
                "RunTime": 0,
                },
            "TodayRunPlan": [],
            "TodayOriginalRunPlan": [],
            "AverageForecastPrice": None,
            "DailyData": [],
        }

        # Now populate some defaults for the DailyData[] dictionary
        for i in range(8):
            date_today = DateHelper.today_add_days(-i)  # Offset the date by i days

            daily_data = {
                "ID": i,
                "Date": date_today.strftime("%Y-%m-%d"),  # Format the date as a string
                "RequiredDailyRuntime": self.helper.get_target_hours(date_today),
                "PriorShortfall": 0,
                "TargetRuntime": None,
                "RuntimeToday": None,
                "RemainingRuntimeToday": None,
                "EnergyUsed": 0,
                "AveragePrice": None,
                "TotalCost": 0,
                "DeviceRuns": [],  # Initialize as an empty list
            }

            self.default_state["DailyData"].append(daily_data)  # Add the dictionary to the list

            # Now add some defaults for the DeviceRuns[] array for prior days
            if i > 0:
                num_runs = 1
                start_time = dt.datetime.strptime(daily_data["Date"], "%Y-%m-%d").replace(tzinfo=local_tz)

                # Make each run last for a num_runs fraction of the target hours for that day less a random shortfall
                run_duration = self.helper.get_target_hours(date_today) / num_runs
                end_time = start_time + dt.timedelta(hours=run_duration)

                for j in range(num_runs):
                    if j == num_runs - 1 and run_duration <= 0:
                        run_duration = 5 / 60
                    price = 20.00
                    run_data = {
                        "ID": j,
                        "StartTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "EndTime": end_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "RunTime": run_duration,
                        "EnergyUsedStart": None,
                        "EnergyUsedForRun": 0,
                        "Price": price,
                        "Cost": 0,
                    }
                    daily_data["DeviceRuns"].append(run_data)

                    start_time += dt.timedelta(hours=run_duration + random.randint(0, 10) / 60)  # Increment the start time for the next run# type: ignore[attr-defined]

        # Now load the latest state from file
        self.load_state()

        # Reset some of the daily data values from current configuration
        for day in self.state["DailyData"]:
            self.set_daily_data(day["ID"], day_data=day)

        # Override values set in config file
        self.state["MaxDailyRuntimeAllowed"] = self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay")
        self.state["DeviceType"] = self.config.get("DeviceType", "Type")
        self.state["DeviceName"] = self.config.get("DeviceType", "Label")
        self.state["LastStatusMessage"] = None

        # See if we need to skip today
        self.skip_run_today = False
        if self.helper.is_no_run_today():
            self.logger.log_message(f"{self.state['DeviceName']} is not scheduled to run today.", "summary")
            self.skip_run_today = True

    def load_state(self):
        """Load the current state from the JSON file."""
        file_path = SCCommon.select_file_location(self.config.get("Files", "SavedStateFile"))  # type: ignore[attr-defined]
        if file_path and file_path.exists():

            try:
                with file_path.open(encoding="utf-8") as file:
                    file_state = json.load(file)
                    self.state = self.helper.merge_configs(self.default_state, file_state)
                    self.logger.log_message(f"Successfully loaded state from {file_path}.", "debug")
            except json.JSONDecodeError as e:
                self.logger.log_fatal_error(f"Error decoding JSON from {file_path}: {e}")

        else:
            self.state = self.default_state

    def save_state(self):
        """Save state to file."""
        local_tz = dt.datetime.now().astimezone().tzinfo

        file_path = SCCommon.select_file_location(self.config.get("Files", "SavedStateFile"))  # type: ignore[attr-defined]
        if not file_path:
            self.logger.log_fatal_error("Unable to determine fill path for saved state file {self.config.get('Files', 'SavedStateFile')}.")
            return

        self.logger.log_message(f"PowerSchedulerState.save_state() Saving state to {file_path}", "debug")
        self.state["LastStateSaveTime"] = dt.datetime.now(local_tz).strftime("%Y-%m-%d %H:%M:%S")

        with file_path.open("w", encoding="utf-8") as file:
            json.dump(self.state, file, indent=4)

        # Now if the WebsiteBaseURL hasbeen set, save the state to the web server
        if self.config.get("DeviceType", "WebsiteBaseURL"):
            api_url = self.config.get("DeviceType", "WebsiteBaseURL") + "/api/submit"  # type: ignore[attr-defined]

            if self.config.get("DeviceType", "WebsiteAccessKey"):
                access_key = self.config.get("DeviceType", "WebsiteAccessKey")
                api_url += f"?key={access_key}"  # Add access_key as a query parameter

            headers = {
                "Content-Type": "application/json",
            }
            json_object = self.state

            try:
                response = requests.post(api_url, headers=headers, json=json_object, timeout=self.config.get("DeviceType", "WebsiteTimeout", default=5))  # type: ignore[attr-defined]
                response.raise_for_status()
                self.logger.log_message(f"Posted PowerSchedulerState to {api_url}", "debug")
            except requests.exceptions.HTTPError as e:
                if response.status_code == HTTP_STATUS_FORBIDDEN:  # Handle 403 Forbidden error
                    self.logger.log_message(f"Access denied ({HTTP_STATUS_FORBIDDEN} Forbidden) when posting to {api_url}. Check your access key or permissions.", "error")
                else:
                    self.logger.log_message(f"HTTP error saving state to web server at {api_url}: {e}", "warning")
            except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
                self.logger.log_message(f"Web server at {api_url} is unavailable. Error was: {e}", "warning")
            except requests.exceptions.RequestException as e:
                self.logger.log_fatal_error(f"Error saving state to web server at {api_url}: {e}")

    def get_daily_data(self, day_number: int) -> dict | None:
        """Returns a dict of the data for the specified day (offset days prior to today). If the day doesn't exist, returns None.

        Args:
            day_number (int): The number of days prior to today (0 for today,

        Returns:
            day_number(dict) | None: The daily data dictionary for the specified day, or None if the day does not exist.
        """
        if 0 <= day_number < len(self.state["DailyData"]):  # Check if day_number is a valid index
            return self.state["DailyData"][day_number]
        return None

    def set_daily_data(self, day_number: int, day_data: dict | None = None) -> bool:
        """Store the dict of the data for the specified day (offset days prior to today).

        Args:
            day_number (int): The number of days prior to today (0 for today, 1 for yesterday, etc.).
            day_data (dict | None): The data to set for the specified day. If None, default values are used.

        Returns:
            result(bool): True if the data was set successfully, False if the day_number is invalid.
        """
        local_tz = dt.datetime.now().astimezone().tzinfo

        if day_number < 0 or day_number > 7:
            self.logger.log_fatal_error(f"Invalid day_number of {day_number} passed.")

        # Set the DailyData element using the passed dict. If that's none, set to default values.
        date_today = dt.datetime.now(local_tz) + dt.timedelta(days=-day_number)  # Offset the date by i days
        if day_data is None:

            today_data = {
                "ID": day_number,
                "Date": date_today.strftime("%Y-%m-%d"),  # Format the date as a string
                "RequiredDailyRuntime": self.helper.get_target_hours(date_today),
                "PriorShortfall": 0,
                "TargetRuntime": None,
                "RuntimeToday": 0,
                "RemainingRuntimeToday": None,
                "EnergyUsed": 0,
                "AveragePrice": None,
                "TotalCost": 0,
                "DeviceRuns": [],  # Initialize as an empty list
            }
            self.state["DailyData"][day_number] = today_data
        else:
            self.state["DailyData"][day_number] = day_data

            # Make sure the ID is correct
            self.state["DailyData"][day_number]["ID"] = day_number

            # make sure the RequiredDailyRuntime is correct
            self.state["DailyData"][day_number]["RequiredDailyRuntime"] = self.helper.get_target_hours(date_today)

        return True

    def consolidate_device_run_data(self, shelly_meter: dict) -> bool:  # noqa: PLR0912
        """Close off any open device runs for today and merge any concurrent DeviceRuns[] elements.

        Args:
            shelly_meter(dict): The ShellyMeter object to use for energy calculations.

        Returns:
            did_close_run (bool): True if there was an open device run that was closed off, False otherwise.
        """
        # Make sure we close off the last DeviceRuns[] entry for each day
        local_tz = dt.datetime.now().astimezone().tzinfo
        did_close_run = False
        for day in self.state["DailyData"]:
            if len(day["DeviceRuns"]) > 0:
                last_run = day["DeviceRuns"][-1]

                if last_run.get("EndTime") is None:  # We have a run that hasn't been closed off yet
                    # If it's a prior day and it wasn't closed off on that day, set end time and duration to 1 sec before midnight
                    did_close_run = True
                    if day["Date"] != DateHelper.today_str():
                        end_time = dt.datetime.strptime(day["Date"], "%Y-%m-%d").astimezone(local_tz) + dt.timedelta(days=1, hours=0, minutes=0, seconds=-1)
                    else:
                        end_time = DateHelper.now()
                    last_run["EndTime"] = DateHelper.format_date(end_time, "%Y-%m-%d %H:%M:%S")
                    last_run["RunTime"] = round((end_time - dt.datetime.strptime(last_run.get("StartTime"), "%Y-%m-%d %H:%M:%S").astimezone(local_tz)).total_seconds() / 3600, 4)

                    # Calaculate energy used for this run since it started if our switch is currently available
                    # Note that price was set in log_device_state()
                    if shelly_meter is None:
                        last_run["EnergyUsedForRun"] = 0
                    else:
                        last_run["EnergyUsedForRun"] = (shelly_meter.get("Energy") or 0) - (last_run.get("EnergyUsedStart") or 0)
                        last_run["Cost"] = (last_run.get("EnergyUsedForRun") or 0) * (last_run.get("Price") or 0) / 1000
                    self.logger.log_message(f"Updated DailyData[{day.get('ID')}].DeviceRuns[{last_run.get('ID')}] with end time {last_run.get('EndTime')}.", "debug")

        # Loop through all the DeviceRuns[] except the last one and see if we need to recalculate the energy used
        todays_data = self.state["DailyData"][0]["DeviceRuns"]
        if len(todays_data) > 1:
            for run_num in range(len(todays_data) - 1):
                this_run = todays_data[run_num]
                next_run = todays_data[run_num + 1]

                if this_run["EnergyUsedForRun"] == 0:
                    this_run["EnergyUsedForRun"] = (next_run.get("EnergyUsedStart") or 0) - (this_run.get("EnergyUsedStart") or 0)
                    this_run["Cost"] = (this_run.get("EnergyUsedForRun") or 0) * (this_run.get("Price") or 0) / 1000

        # Aggregate the DeviceRuns[] data each day including today
        for day in self.state["DailyData"]:
            consolidated_device_runs = []
            new_device_run = None
            new_device_run_idx = 0
            for this_run in day["DeviceRuns"]:
                # If we don't have a run in play, or the start time of this run 1 min after the end time of
                # the last run, then create a new consolidated element
                start_time = dt.datetime.strptime(this_run["StartTime"], "%Y-%m-%d %H:%M:%S").astimezone(local_tz)
                if new_device_run is not None:
                    end_time = dt.datetime.strptime(new_device_run.get("EndTime"), "%Y-%m-%d %H:%M:%S").astimezone(local_tz)  # type: ignore[attr-defined]
                else:
                    end_time = None
                if new_device_run is None or end_time is None or (start_time - end_time).total_seconds() > 60:

                    # Create a new consolidated run object that we will add to the array
                    new_device_run = {
                        "ID": new_device_run_idx,
                        "StartTime": this_run.get("StartTime"),
                        "EndTime": this_run.get("EndTime"),
                        "RunTime": this_run.get("RunTime"),
                        "EnergyUsedStart": this_run.get("EnergyUsedStart") or 0,
                        "EnergyUsedForRun": this_run.get("EnergyUsedForRun") or 0,
                        "Price": this_run.get("Price") or 0,
                        "Cost": this_run.get("Cost") or 0,
                    }
                    # Add this new run to the consolidated list
                    consolidated_device_runs.append(new_device_run)
                    new_device_run_idx += 1
                else:
                    # Extend the existing consolidated run object - the new_device_run object previously added to the consolidated array
                    consolidated_device_runs[new_device_run_idx - 1]["EndTime"] = this_run.get("EndTime")
                    consolidated_device_runs[new_device_run_idx - 1]["RunTime"] += this_run.get("RunTime")
                    consolidated_device_runs[new_device_run_idx - 1]["EnergyUsedForRun"] += this_run.get("EnergyUsedForRun") or 0
                    consolidated_device_runs[new_device_run_idx - 1]["Cost"] += this_run.get("Cost") or 0
                    if consolidated_device_runs[new_device_run_idx - 1]["Cost"] > 0 and consolidated_device_runs[new_device_run_idx - 1]["EnergyUsedForRun"] > 0:
                        consolidated_device_runs[new_device_run_idx - 1]["Price"] = round(consolidated_device_runs[new_device_run_idx - 1]["Cost"] / (consolidated_device_runs[new_device_run_idx - 1]["EnergyUsedForRun"] / 1000), 2)
                    else:
                        consolidated_device_runs[new_device_run_idx - 1]["Price"] = None

            # Got through the list of original runs. Replaced DeviceRuns entry
            day["DeviceRuns"].clear()
            day["DeviceRuns"] = consolidated_device_runs

        # Return True if there was an open device
        return did_close_run

    def is_device_run_open(self) -> bool:
        """Check if there are any open device runs.

        Returns:
            run_open(bool): True if there is an open device run, False otherwise.
        """
        data_today = self.state["DailyData"][0]
        device_open = False

        if len(data_today["DeviceRuns"]) > 0:
            last_run = data_today["DeviceRuns"][-1]
            if last_run["EndTime"] is None:
                device_open = True

        return device_open

    def calculate_running_totals(self):  # noqa: PLR0915
        """Confirm that no day rollover is needed."""
        if self.state["DailyData"][0]["Date"] != DateHelper.today_str():
            self.logger.log_fatal_error("called when DailyData[0] was not today")

        # Current date and time
        now = DateHelper.now()

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
            elif self.config.get("DeviceType", "Type") == "HotWaterSystem":
                day_data["TargetRuntime"] = day_data["RequiredDailyRuntime"]
            else:
                day_data["TargetRuntime"] = day_data["RequiredDailyRuntime"] + day_data["PriorShortfall"]
                day_data["TargetRuntime"] = max(day_data["TargetRuntime"], self.config.get("DeviceRunScheule", "MinimumRunHoursPerDay", default=3))  # type: ignore[attr-defined]
                day_data["TargetRuntime"] = min(day_data["TargetRuntime"], self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay", default=9))  # type: ignore[attr-defined]

            # Calculate running_shortfall to be used for the next day
            if self.config.get("DeviceType", "Type") == "PoolPump":
                running_shortfall += day_data["RequiredDailyRuntime"] - day_data["RuntimeToday"]

            # And the global running totals
            if day_data["ID"] > 0:
                self.state["TotalRuntimePriorDays"] += day_data["RuntimeToday"] or 0
            self.state["EnergyUsed"] += day_data["EnergyUsed"] or 0
            self.state["TotalCost"] += day_data["TotalCost"] or 0

        # Finally the remaining aggregate values
        self.state["AverageRuntimePriorDays"] = self.state["TotalRuntimePriorDays"] / 7
        if self.state["EnergyUsed"] > 0:
            self.state["AveragePrice"] = self.state["TotalCost"] / (self.state["EnergyUsed"] / 1000)
        self.state["CurrentShortfall"] = max(0, running_shortfall)
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

        midnight = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
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

    def check_day_rollover(self) -> bool:
        """Check if a new day has started and update history accordingly.

        Returns:
            result(bool): True if a rollover was detected and processed, False otherwise.
        """
        # Check if the date for the first element in DailyData is prior to today
        current_date = DateHelper.today_str()  # Get today's date in YYYY-MM-DD format
        daily_data = self.get_daily_data(0)     # Get the daily data for today if any
        if daily_data is None:
            # We have no daily data for today, nothing to do yet
            return False
        # See if date for 0 element is prior to today
        if daily_data["Date"] == current_date:
            return False

        self.logger.log_message("PowerSchedulerState.check_day_rollover(): New day detected, rolling data over to prior days.", "debug")

        # First increment the EarlierTotals for the oldest date that we're loosing
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
        """Check if the energy used yesterday was more than expected."""
        # Get the daily data for yesterday
        yesterday_data = self.get_daily_data(1)
        if yesterday_data is None:
            self.logger.log_message("PowerSchedulerState.check_yesterday_energy_usage(): No data for yesterday.", "warning")
            return

        # Check if the energy used was less than expected
        threashold = self.config.get("Email", "DailyEnergyUseThreshold") or 0
        if threashold > 0 and yesterday_data["EnergyUsed"] > threashold:  # type: ignore[attr-defined]
            warning_msg = f"{self.state['DeviceName']} energy used on {yesterday_data['Date']} was {yesterday_data['EnergyUsed']:.0f} watts, which exceeded the expected limit of {threashold}."
            self.logger.log_message(warning_msg, "warning")

            # Send an email notification if configured
            self.logger.send_email("Energy Usage Alert", warning_msg)

    def set_current_price(self, price):
        """Sets the current price in the state dictionary."""
        self.state["CurrentPrice"] = price
        self.state["PriceTime"] = DateHelper.now_str("%Y-%m-%d %H:%M:00")

    def __getitem__(self, index) -> Any:
        """Allows access to the state dictionary using square brackets.

        Args:
            index: The key to access in the state dictionary.

        Returns:
            The value associated with the key in the state dictionary.
        """
        return self.state.get(index)

    def __setitem__(self, index, value):
        """Allows setting values in the state dictionary using square brackets."""
        self.state[index] = value
