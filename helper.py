"""General purpose helper functions for the Amber Power Controller."""

import datetime as dt

import requests
from sc_utility import DateHelper, SCConfigManager, SCLogger


class AmberHelper:
    """General purpose helper functions for the Amber Power Controller."""

    def __init__(self, config: SCConfigManager, logger: SCLogger):
        """Initialize the AmberHelper with a configuration and logger.

        Args:
            config (SCConfigManager): The configuration dictionary containing device settings.
            logger (SCLogger): An instance of a logger to log messages.
        """
        self.config = config
        self.logger = logger

    def is_no_run_today(self) -> bool:
        """Check if today is a no run day.

        Returns:
            result(bool): True if today is a no run day, otherwise False.
        """
        # Get the current date
        date_today = DateHelper.today()
        # Get the no run periods from the config
        device_run_schedule = self.config.get("DeviceRunScheule")
        if device_run_schedule is not None and "NoRunPeriods" in device_run_schedule:
            no_run_periods = device_run_schedule.get("NoRunPeriods")

            if no_run_periods is not None:
                # Check if today falls within any of the no run periods
                for period in no_run_periods:
                    if period["StartDate"] <= date_today <= period["EndDate"]:
                        return True
        return False

    def get_target_hours(self, for_date: dt.date | None = None) -> int:
        """
        Get the target run hours for the given date.

        Args:
            for_date (Optional(date), optional): The date for which to get the target run hours. If None, defaults to today.

        Returns:
            target_hours(int): The target run hours for the given date.
        """
        if for_date is None:
            for_date = DateHelper.today()

        if self.is_no_run_today():
            # If today is a no run day, return 0
            target_hours = 0
        elif self.config.get("DeviceType", "Type") == "HotWaterSystem":
            # For hot water systems, our target run time is 24 hours
            target_hours = 24
        else:
            # For pool pumps, we need to check the config for the target run hours

            target_hours = self.config.get("DeviceRunScheule", "TargetRunHoursPerDay", default=6)
            assert isinstance(target_hours, int), "Target run hours must be an integer"
            device_label = self.config.get("DeviceType", "Label")
            month = for_date.strftime("%B")

            device_run_schedule = self.config.get("DeviceRunScheule")
            monthly_target_run_hours_per_day = self.config.get("DeviceRunScheule", "MonthlyTargetRunHoursPerDay")
            if (device_run_schedule is not None and
                "MonthlyTargetRunHoursPerDay" in device_run_schedule and
                monthly_target_run_hours_per_day is not None and
                month in monthly_target_run_hours_per_day
            ):
                target_hours = self.config.get("DeviceRunScheule", "MonthlyTargetRunHoursPerDay", month)

            # Now make sure the override is within the min/max range
            min_run_hours_per_day = self.config.get("DeviceRunScheule", "MinimumRunHoursPerDay", default=3)
            assert isinstance(min_run_hours_per_day, int)
            max_run_hours_per_day = self.config.get("DeviceRunScheule", "MaxiumumRunHoursPerDay", default=9)
            assert isinstance(max_run_hours_per_day, int)
            # Ensure target_hours is an integer before comparison
            if isinstance(target_hours, int) and min_run_hours_per_day is not None and target_hours < min_run_hours_per_day:
                target_hours = min_run_hours_per_day
                if self.logger is not None:
                    self.logger.log_message(f"{device_label} target daily run hours for {month} are too short. Resetting to the minimum of {target_hours}", "warning")
            elif isinstance(target_hours, int) and max_run_hours_per_day is not None and target_hours > max_run_hours_per_day:
                target_hours = self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay")
                if self.logger is not None:
                    self.logger.log_message(f"{device_label} target daily run hours for {month} are too long. Resetting to the maximum of {target_hours}", "warning")

        return target_hours  # type: ignore[return-value]

    def merge_configs(self, default: dict, custom: dict) -> dict:
        """Merges two dictionaries recursively, with the custom dictionary.

        Args:
            default (dict): The default configuration dictionary.
            custom (dict): The custom configuration dictionary to merge into the default.

        Returns:
            merged(dict): The merged configuration dictionary.
        """
        for key, value in custom.items():
            if isinstance(value, dict) and key in default:
                self.merge_configs(default[key], value)
            else:
                default[key] = value
        return default

    def ping_heatbeat(self, is_fail: bool | None = None) -> bool:  # noqa: FBT001
        """Ping the heartbeat URL to check if the service is available.

        Args:
            is_fail (bool, optional): If True, the heartbeat will be considered a failure.

        Returns:
            bool: True if the heartbeat URL is reachable, False otherwise.
        """
        heartbeat_url = self.config.get("HeartbeatMonitor", "WebsiteURL")
        timeout = self.config.get("HeartbeatMonitor", "HeartbeatTimeout", default=10)

        if heartbeat_url is None:
            self.logger.log_message("Heartbeat URL not configured - skipping sending a heatbeat.", "debug")
            return True
        assert isinstance(heartbeat_url, str), "Heartbeat URL must be a string"

        if is_fail:
            heartbeat_url += "/fail"

        try:
            response = requests.get(heartbeat_url, timeout=timeout)  # type: ignore[call-arg]
        except requests.exceptions.Timeout as e:
            self.logger.log_message(f"Timeout making Heartbeat ping: {e}", "error")
            return False
        except requests.RequestException as e:
            self.logger.log_fatal_error(f"Heartbeat ping failed: {e}")
            return False
        else:
            if response.status_code == 200:
                self.logger.log_message("Heartbeat ping successful.", "debug")
                return True
            self.logger.log_message(f"Heartbeat ping failed with status code: {response.status_code}", "error")
            return False
