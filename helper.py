"""General purpose helper functions for the Amber Power Controller."""

from datetime import datetime


class AmberHelper:
    """General purpose helper functions for the Amber Power Controller."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger


    def is_no_run_today(self):
        """Check if today is a no run day."""
        # Get the current date
        local_tz = datetime.now().astimezone().tzinfo
        date_today = datetime.now(local_tz).strftime("%Y-%m-%d")

        # Get the no run periods from the config
        if "NoRunPeriods" in self.config.get("DeviceRunScheule"):
            no_run_periods = self.config.get("DeviceRunScheule", "NoRunPeriods")

            if no_run_periods is not None:
                # Check if today falls within any of the no run periods
                for period in no_run_periods:
                    if period["StartDate"] <= date_today <= period["EndDate"]:
                        return True
        return False

    def get_target_hours(self, for_date):
        """
        Returns the target run hours for the given date.

        :param for_date: The date for which to get the target run hours. Defaults to today.
        :return: The target run hours for the given date.
        """
        local_tz = datetime.now().astimezone().tzinfo
        if for_date is None:
            for_date = datetime.now(local_tz)

        if self.is_no_run_today():
            # If today is a no run day, return 0
            target_hours = 0
        elif self.config.get("DeviceType", "Type") == "HotWaterSystem":
            # For hot water systems, our target run time is 24 hours
            target_hours = 24
        else:
            # For pool pumps, we need to check the config for the target run hours

            target_hours = self.config.get("DeviceRunScheule", "TargetRunHoursPerDay")
            device_label = self.config.get("DeviceType", "Label")
            month = for_date.strftime("%B")

            if ("MonthlyTargetRunHoursPerDay" in self.config.get("DeviceRunScheule")
                and month
                in self.config.get("DeviceRunScheule", "MonthlyTargetRunHoursPerDay")
            ):
                target_hours = self.config.get("DeviceRunScheule", "MonthlyTargetRunHoursPerDay", month)

            # Now make sure the override is within the min/max range
            if (
                target_hours
                < self.config.get("DeviceRunScheule", "MinimumRunHoursPerDay")
            ):
                target_hours = self.config.get("DeviceRunScheule", "MinimumRunHoursPerDay")
                if self.logger is not None:
                    self.logger.log_message(f"{device_label} target daily run hours for {month} are too short. Resetting to the minimum of {target_hours}","warning")
            elif (
                target_hours
                > self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay")
            ):
                target_hours = self.config.get("DeviceRunScheule", "MaximumRunHoursPerDay")
                if self.logger is not None:
                    self.logger.log_message(f"{device_label} target daily run hours for {month} are too long. Resetting to the maximum of {target_hours}","warning")

        return target_hours

    def merge_configs(self, default, custom):
        """Merges two dictionaries recursively, with the custom dictionary."""
        for key, value in custom.items():
            if isinstance(value, dict) and key in default:
                self.merge_configs(default[key], value)
            else:
                default[key] = value
        return default

