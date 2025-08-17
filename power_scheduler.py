"""PowerScheduler class to manage the device scheduling based on electricity prices."""

import datetime as dt
import inspect
import math

from sc_utility import CSVReader, DateHelper, SCCommon, SCConfigManager, SCLogger

from config_schemas import ConfigSchema
from power_scheduler_state import PowerSchedulerState
from price_data import PriceData


class PowerScheduler:
    """Class to manage the device scheduling based on electricity prices."""

    def __init__(self, config: SCConfigManager, schemas: ConfigSchema, logger: SCLogger):
        """Initialise the PowerScheduler class.

        Args:
            config (SCConfigManager): The configuration manager instance.
            schemas (ConfigSchema): The configuration schemas.
            logger (SCLogger): The logger instance.
        """
        self.config = config
        self.logger = logger
        self.csv_header_config = schemas.csv_header_config

        # Create an instance of the PowerScheduleState dictionary and load the prior state from file
        self.state = PowerSchedulerState(config, logger)

        # Initialize the ShellyControl instance
        self.shelly_control = None
        self.shelly_device = {}
        self.shelly_output = {}
        self.shelly_meter = {}

        # Log a warning it it's been more than 30 mins since the last state save
        last_state_save_time = self.state["LastStateSaveTime"]
        if last_state_save_time is not None:
            last_state_save_time = DateHelper.parse_date(last_state_save_time, "%Y-%m-%d %H:%M:%S")
            time_diff = DateHelper.now() - last_state_save_time   # type: ignore[operator]
            if time_diff.total_seconds() > 1800:
                self.logger.log_message(f"{self.state['DeviceName']} last run time was {time_diff.total_seconds() / 3600:.1f} hours ago. This is too long - please run at least every 30 minutes.", "warning")

        # Check if we have a working internet connection
        self.have_internet = SCCommon.check_internet_connection()
        if not self.have_internet:
            self.logger.log_message("No internet connection detected. Some features may not work.", "warning")

        # Figure out the all time average price if available
        average_price = self.state["AlltimeTotals"]["AveragePrice"]
        if average_price is None:
            average_price = 15.0

        # Create an instance of the PriceData class and get the latest prices for the remainder of today
        last_api_error_count = self.state["AmberAPIErrorCount"] or 0
        self.price_data = PriceData(config, logger, last_api_error_count, average_price)

        # Aow see how many concurrent API errors we have
        last_api_error_count = self.price_data.get_api_error_count()
        # And save this to the state
        self.state["AmberAPIErrorCount"] = last_api_error_count

        # record whether we have live prices or not
        self.state["LivePrices"] = self.price_data.have_live_prices()
        if not self.state["LivePrices"]:
            self.logger.log_message("Live prices are not available.", "debug")

        # Save latest price
        current_price = self.price_data.get_current_price()
        self.state.set_current_price(current_price)

    def register_shelly_control(self, shelly_control):
        """Register the ShellyControl class with the scheduler.

        Args:
            shelly_control (ShellyControl): The ShellyControl instance to register.
        """
        self.shelly_control = shelly_control
        try:
            self.shelly_output = shelly_control.get_device_component("output", self.config.get("DeviceType", "Switch"))
            if self.config.get("DeviceType", "Meter"):
                self.shelly_meter = shelly_control.get_device_component("meter", self.config.get("DeviceType", "Meter"))
            self.shelly_device = shelly_control.devices[self.shelly_output.get("DeviceIndex")]
        except RuntimeError as e:
            self.logger.log_fatal_error(f"Error registering ShellyControl: {e}")
        else:
            self.logger.log_message(f"Registered ShellyControl for {self.state['DeviceName']}.", "debug")

    def refresh_shelly_status(self):
        """Refresh the status of the Shelly device."""
        if self.shelly_control is None or not self.shelly_device:
            self.logger.log_fatal_error("ShellyControl not registered. Cannot refresh status.")
            return

        try:
            self.shelly_control.get_device_status(self.shelly_device)
        except TimeoutError:
            self.logger.log_message(f"Refresh of Shelly status for {self.shelly_device['ClientName']} failed - device offline.", "warning")
        except RuntimeError as e:
            self.logger.log_fatal_error(f"Error refreshing Shelly status: {e}")
        else:
            self.logger.log_message(f"Refreshed Shelly status for {self.shelly_device['ClientName']}.", "debug")

    def change_switch(self, new_state: bool) -> tuple[bool, bool, bool]:  # type: ignore[return] # noqa: FBT001
        """Change the state of the switch based on the new_state flag.

        Args:
            new_state (bool): True to turn the switch on, False to turn it off.

        Returns:
            result(bool): True if the switch state was changed successfully, False otherwise.
            did_change (bool): True if the switch state was changed, False if it was already in the desired state.
            new_state (bool): The new state of the switch after the change.
        """
        if self.shelly_control is None or self.shelly_device is None or self.shelly_output is None:
            self.logger.log_fatal_error("ShellyControl not registered. Cannot change switch state.")
            return False, False, False

        if not self.shelly_device["Online"]:
            self.logger.log_message(f"{self.state['DeviceName']} is offline. Cannot change switch state.", "warning")
            return False, False, False

        try:
            result, did_change = self.shelly_control.change_output(self.shelly_output, new_state)
        except TimeoutError:
            self.logger.log_message(f"Change of Shelly switch for {self.shelly_device['ClientName']} failed - device offline.", "warning")
            return False, False, self.shelly_output.get("State", False)
        except RuntimeError as e:
            self.logger.log_fatal_error(f"Error changing switch state: {e}")
        else:
            new_state = self.shelly_output.get("State", False)
            return result, did_change, new_state

    def validate_device_state(self) -> bool:
        """Validate the state of the PowerScheduler object.

        Returns:
            result (bool): True if the device state is valid, otherwise False.
        """
        if self.shelly_device is None or self.shelly_output is None:
            self.logger.log_fatal_error("Called when ShellyControl is not registered.")
            return False

        if self.shelly_output.get("State", False) != self.state["IsDeviceRunning"]:
            self.logger.log_message(f"{self.state['DeviceName']} switch has been changed externally since the PowerController last stated. Switch on: {self.shelly_output.get('State')} but we last set the switch to {self.state['IsDeviceRunning']}", "warning")

        # Check to see how long the pool device has been running for
        if self.state["IsDeviceRunning"] and self.config.get("DeviceType", "Type") == "PoolPump":
            start_time = DateHelper.parse_date(self.state["DeviceLastStartTime"], "%Y-%m-%d %H:%M:%S")
            assert isinstance(start_time, dt.datetime)
            max_hours = self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay", default=9)
            running_hours = int((DateHelper.now() - start_time).total_seconds() / 3600)
            if running_hours > max_hours:  # type: ignore[comparison-overlap]
                self.logger.log_message(f"{self.state['DeviceName']} appears to have been running for {running_hours:.1f} hours, more than maximum of {max_hours} hours. This should never happen. ", "error")

                # Reset the start time so that we don't get this error every time
                self.state["DeviceLastStartTime"] = DateHelper.format_date(DateHelper.now(), "%Y-%m-%d %H:%M:%S")
                return False

        return True

    def should_device_run(self) -> bool:
        """Determines if the device should run in the current slot.

        Returns:
            should_run (bool): True if the device should run, False otherwise.
        """
        # Calculate how many slots we need to run today
        required_slots, selected_slots = self.calculate_required_slots()

        run_device = False
        self.state["TodayRunPlan"].clear()

        if selected_slots > 0:
            run_device, reason_why_message, override_message = self.evaluate_run_conditions()

            self.record_run_plan(run_device, selected_slots, reason_why_message, override_message)
        else:
            if self.state.skip_run_today:  # If we're scheduled to skip today, then we don't run the device
                status_message = f"{self.state['DeviceName']} is scheduled to not run today."
            elif required_slots > 0:
                status_message = f"All remaining time slots for today are too expensive. {self.state['DeviceName']} will not run."
            else:
                status_message = f"No runtime needed - {self.state['DeviceName']} will not run."

            # Save the status message
            self.state["LastStatusMessage"] = status_message
            self.logger.log_message(status_message, "summary")

        # Save the run plan to the file
        self.state.save_state()
        return run_device

    def calculate_required_slots(self) -> tuple[int, int]:
        """Calculate the required slots and identify the cheapest slots.

        Returns:
            required_slots (int): The number of slots that we need to run today.
            selected_slots (int): The number of slots that we have actually selected.
        """
        available_slots = len(self.price_data.prices)
        remaining_hours = self.state["DailyData"][0]["RemainingRuntimeToday"]
        required_slots = math.ceil(remaining_hours * 2)
        required_slots = min(required_slots, available_slots)  # Don't exceed available slots
        live_prices = self.price_data.have_live_prices()

        # Flag the slots in prices array that we need
        selected_slots = 0
        for idx in range(required_slots):
            # Only select the price if its less than the maximum price or we don't have live price data
            if self.price_data.prices_sorted[idx]["Price"] <= self.config.get("DeviceRunScheule", "MaximumPriceToRun") or not live_prices:
                self.price_data.prices_sorted[idx]["Selected"] = True
                slot = self.price_data.prices_sorted[idx]["Slot"]
                self.price_data.prices[slot]["Selected"] = True
                selected_slots += 1
            else:
                self.logger.log_message(f"Price {self.price_data.prices_sorted[idx]['Price']:.1f} c/kWh for {self.price_data.prices_sorted[idx]['StartTime']} exceeds maximum price of {self.config.get('DeviceRunScheule', 'MaximumPriceToRun')} c/kWh. We were only able to pick {selected_slots} of the {required_slots} required slots", "detailed")
                break

        # Make note of the maximum runtime left today based on selected slots
        self.state["ForecastRuntimeToday"] = selected_slots / 2

        return required_slots, selected_slots

    def flag_current_slot(self, is_selected: bool):  # noqa: FBT001
        """Flag the Selected attribute in the curent price slot.

        Args:
            is_selected (bool): True if the current slot is selected, False otherwise.
        """
        self.price_data.prices_sorted[0]["Selected"] = is_selected
        slot = self.price_data.prices_sorted[0]["Slot"]
        self.price_data.prices[slot]["Selected"] = is_selected

    def evaluate_run_conditions(self) -> tuple[bool, str, str | None]:
        """Evaluate the conditions to determine if the device should run.

        Returns:
            run_device (bool): True if the device should run, False otherwise.
            reason_why_message (str): Reason why the device will or won't run.
            override_message (str): Message indicating if the device is overridden from running. Can be None
        """
        # Get the worst price and current price
        worst_price = self.price_data.get_worst_price()
        current_price = self.price_data.get_current_price()
        reason_why_message = None
        override_message = None

        if self.shelly_device is None or self.shelly_output is None:
            self.logger.log_fatal_error("Called when ShellyControl is not registered.")
            return False, "", ""

        # If the switch is unable to run, then we can't run it
        if not self.shelly_device["Online"]:
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
            min_hours = self.config.get("DeviceRunScheule", "MinimumRunHoursPerDay")
            excess_threashold = self.config.get("DeviceRunScheule", "ThresholdAboveCheapestPricesForMinumumHours", default=1.2)
            assert isinstance(excess_threashold, float)
            if today_runtime < min_hours and current_price < worst_price * excess_threashold:  # type: ignore[comparison-overlap]
                run_device = True
                reason_why_message = (f"we haven't run the device for at least {min_hours} hours today and the"
                                        f" current price is less than the most expensive price in our chosen"
                                        f" slots plus {round((excess_threashold - 1), 2) * 100:.0f}%")

            # If the device is a pool pump, check if it has been running for too long today
            if self.config.get("DeviceType", "Type") == "PoolPump":
                max_hours = self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay")
                if today_runtime >= max_hours:
                    if run_device:
                        override_message = f"maximum daily runtime of {max_hours} hours reached."
                    run_device = False

            # If we don't have live prices, then don't run if we're outside the scheduled time range
            if not self.price_data.have_live_prices() and not self.inside_manual_schedule():
                if run_device:
                    override_message = "live prices unavailable and not inside the manual scheduled time range"
                run_device = False

        # Make sure the current price slot is properly flagged
        self.flag_current_slot(run_device)
        return run_device, reason_why_message, override_message

    def inside_manual_schedule(self, time_to_check: dt.time | None = None) -> bool:
        """Check if the current time is within the manual schedule.

        Args:
            time_to_check (dt.time, optional): The time to check against the manual schedule. Defaults to None, which uses the current time.

        Returns:
            bool: True if the current time is within the manual schedule, False otherwise.
        """
        if time_to_check is None:
            time_to_check = DateHelper.now().time()

        manual_schedule = self.config.get("DeviceRunScheule", "ManualSchedule")
        local_tz = dt.datetime.now().astimezone().tzinfo

        # If no manual schedule is configured, return True
        if not manual_schedule:
            return True

        # Iterate through each schedule entry
        for schedule_entry in manual_schedule:
            start_time_str = schedule_entry.get("StartTime")
            end_time_str = schedule_entry.get("EndTime")

            # Skip if either start or end time is missing
            if not start_time_str or not end_time_str:
                continue

            try:
                # Parse the time strings (format: "HH:MM")
                start_time = dt.datetime.strptime(start_time_str, "%H:%M").replace(tzinfo=local_tz).time()
                end_time = dt.datetime.strptime(end_time_str, "%H:%M").replace(tzinfo=local_tz).time()

                # Check if time_to_check falls within this range
                if start_time <= time_to_check <= end_time:
                    return True

            except ValueError as e:
                self.logger.log_message(f"Invalid time format in ManualSchedule: {e}", "warning")
                continue

        return False

    def record_run_plan(self, run_device: bool, selected_slots: int, reason_why_message: str, override_message: str | None):  # noqa: FBT001, PLR0915
        """Record the run plan for the device based on the calculated slots and conditions.

        Args:
            run_device (bool): True if the device should run, False otherwise.
            selected_slots (int): The number of slots that have been selected for running.
            reason_why_message (str): Reason why the device will or won't run.
            override_message (str): Message indicating if the device is overridden from running.
        """
        # Clear out any prior run plan
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
                end_time = DateHelper.parse_date(price["EndTime"], "%Y-%m-%d %H:%M:%S")
                assert isinstance(end_time, dt.datetime)

                # If the prior slot was selected as well then it's concurrent
                if price_idx > 0 and self.price_data.prices[price_idx - 1]["Selected"]:
                    concurrent_count += 1
                    total_price += price["Price"]

                    # Update the existing entry
                    self.state["TodayRunPlan"][i - 1]["To"] = end_time.strftime("%H:%M")
                    self.state["TodayRunPlan"][i - 1]["AveragePrice"] = round(total_price / concurrent_count, 2)
                else:
                    # There's a gap since the last once, so add a new entry
                    total_price = price["Price"]
                    concurrent_count = 1
                    start_time = DateHelper.parse_date(price["StartTime"], "%Y-%m-%d %H:%M:%S")
                    assert isinstance(start_time, dt.datetime)
                    run_item = {
                        "ID": i,
                        "From": start_time.strftime("%H:%M"),
                        "To": end_time.strftime("%H:%M"),
                        "AveragePrice": round(total_price / concurrent_count, 2),
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
        average_forecast_price /= selected_slots
        self.state["AverageForecastPrice"] = average_forecast_price

        # If we haven't logged any runs today, save a copy of the run plan
        if len(self.state["DailyData"][0]["DeviceRuns"]) == 0:
            self.state["TodayOriginalRunPlan"] = self.state["TodayRunPlan"].copy()

        today_runtime = self.state["DailyData"][0]["RuntimeToday"]
        run_device_str = "on" if run_device else "off"
        final_message = f"{self.state['DeviceName']} switch is {run_device_str}. Target: {self.state['DailyData'][0]['TargetRuntime']:.2f} hours. "
        final_message += f"Actual: {today_runtime:.2f} hours. Planned: {self.state['ForecastRuntimeToday']:.2f}. Price now: {self.price_data.prices[0]['Price']:.2f} c/kWh."
        final_message += f" Average forecast price: {average_forecast_price:.2f} c/kWh. "

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
        if device_run_plan_msg:
            final_message += f" {self.state['DeviceName']} run plan:\n{device_run_plan_msg}"

        self.logger.log_message(final_message, "summary")
        if self.config.get("Email", "SendSummary"):
            subject = f"{self.state['DeviceName']} scheduler Summary for {DateHelper.now_str()}"
            self.logger.send_email(subject, final_message)

    def log_device_state(self, did_change: bool, new_outout_state: bool):  # noqa: FBT001
        """Record the state change of the device switch.

        Args:
            did_change (bool): True if the switch state was changed, False if it was already in the desired state.
            new_outout_state (bool): The new state of the switch after the change.
        """
        current_frame = inspect.currentframe()
        function_name = self.__class__.__name__ + "." + (current_frame.f_code.co_name if current_frame else "unknown") + "()"

        # old_device_state and new_device_state are instances of ShellySwitchState
        if not self.shelly_device["Online"]:
            self.logger.log_message(f"Starting {function_name} - switch is currently offline - updating system status.", "debug")
            self.state["IsDeviceRunning"] = False
            self.state["DeviceLastStartTime"] = None
        else:
            # Should never be called if the device run is open
            if self.state.is_device_run_open():
                self.logger.log_fatal_error("called with an open device run.")

            # Record the device being turned on or turned off
            self.logger.log_message(f"Starting {function_name} - was changed: {did_change} new state: {new_outout_state}.", "debug")

            # If the device is running, add a new run entry
            if self.shelly_output and self.shelly_output.get("State"):
                run_num = len(self.state["DailyData"][0]["DeviceRuns"])
                if did_change:
                    self.logger.log_message(f"Turning the {self.state['DeviceName']} on, starting run {run_num + 1}.", "summary")

                run_item = {
                    "ID": len(self.state["DailyData"][0]["DeviceRuns"]),
                    "StartTime": DateHelper.now_str(),
                    "EndTime": None,
                    "RunTime": None,
                    "EnergyUsedStart": (self.shelly_meter.get("Energy") or 0) if self.shelly_meter else None,
                    "EnergyUsedForRun": None,
                    "Price": round(self.state["CurrentPrice"], 2),
                    "Cost": None,
                }
                self.state["DailyData"][0]["DeviceRuns"].append(run_item)

                self.state["IsDeviceRunning"] = True
                if self.state["DeviceLastStartTime"] is None:
                    self.state["DeviceLastStartTime"] = DateHelper.now_str()
                    self.state["EnergyAtLastStart"] = (self.shelly_meter.get("Energy") or 0) if self.shelly_meter else None
            else:   # Device is not running
                run_num = len(self.state["DailyData"][0]["DeviceRuns"])
                if did_change:
                    self.logger.log_message(f"Turning the {self.state['DeviceName']} off, closing out run {run_num}.", "summary")

                self.state["IsDeviceRunning"] = False
                self.state["DeviceLastStartTime"] = None
        self.state.save_state()

        # Finally log the daily stats
        self.log_daily_stats()

    def send_heartbeat(self, is_fail: bool | None = None) -> bool:  # noqa: FBT001
        """Send a heartbeat signal to the monitoring system.

        Args:
            is_fail (bool, optional): If True, the heartbeat will be considered a failure.

        Returns:
            bool: True if the heartbeat URL is reachable, False otherwise.
        """
        return self.state.helper.ping_heatbeat(is_fail)

    def log_daily_stats(self) -> bool:
        """Log the daily statistics for the device.

        Returns:
            bool: True if the data was saved successfully, False otherwise.
        """
        csv_filename = self.config.get("Files", "DailyRunStatsCSV")
        if not csv_filename:
            self.logger.log_message("DailyRunStatsCSV is not configured. Skipping daily stats logging.", "debug")
            return False
        csv_path = SCCommon.select_file_location(csv_filename)  # type: ignore[attr-defined]
        if not csv_path:
            self.logger.log_message("Failed to select file location for DailyRunStatsCSV. Skipping daily stats logging.", "error")
            return False

        # Create the dict object for our daily data
        daily_data = {
            "Date": DateHelper.today(),
            "DeviceName": self.state["DeviceName"],
            "CurrentState": self.state["IsDeviceRunning"],
            "TargetRuntime": self.state["DailyData"][0]["TargetRuntime"],
            "RuntimeToday": self.state["DailyData"][0]["RuntimeToday"] or 0,
            "RemainingRuntimeToday": self.state["DailyData"][0]["RemainingRuntimeToday"],
            "EnergyUsage": self.state["DailyData"][0]["EnergyUsed"] or 0,
            "EnergyCost": self.state["DailyData"][0]["TotalCost"] or 0,
            "AveragePrice": round(self.state["DailyData"][0]["AveragePrice"] or 0, 2),
        }
        data_list = []
        data_list.append(daily_data)

        # First entry in header_config is the Date column
        days_to_save = self.config.get("Files", "DailyRunStatsDaysToKeep", default=365)
        self.csv_header_config[0]["minimum"] = DateHelper.today_add_days(-days_to_save)  # type: ignore[attr-defined]

        # Create an instance of the CSVReader class and write the new file
        try:
            csv_reader = CSVReader(csv_path, self.csv_header_config)
            csv_reader.update_csv_file(data_list)
        except (ImportError, TypeError, ValueError, RuntimeError) as e:
            self.logger.log_fatal_error(f"Failed to write CSV file {csv_path}: {e}")

        return True
