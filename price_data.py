"""Manage the integration with Amber API to fetch and process price data."""
import datetime as dt
import json
import operator
from collections import OrderedDict
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from sc_utility import DateHelper, SCCommon, SCConfigManager, SCLogger


class PriceData:
    """Class to manage the Amber price data for the device scheduler."""

    def __init__(self, config: SCConfigManager, logger: SCLogger, average_price: float = 15.0):
        """
        Initialise the PriceData class.

        Args:
            config (SCConfigManager): The configuration manager instance.
            logger (SCLogger): The logger instance for logging messages.
            average_price (float): The average price to use in mock mode, default is 15.0 AUD/kWh.
        """
        self.config = config
        self.logger = logger
        self.prices = []
        self.prices_sorted = []
        self.mode = "live"  # Default mode is live, will be set to mock if no internet or no Amber configuration or no Amber site ID

        if not SCCommon.check_internet_connection():
            self.mode = "mock"
            self.logger.log_message("No internet connection detected. Using mock mode for electricity prices.", "warning")
        elif not self.config.get("AmberAPI", "APIKey"):
            self.mode = "mock"
            self.logger.log_message("Amber API not configured. Using mock mode for electricity prices.", "warning")
        else:
            # Get the Amber site ID.
            self.site_id = self.get_site_id()

            # If we returned None, there assume we have no internet connectivity
            if self.site_id is None:
                self.logger.log_message("No Amber site information available. Using mock mode for electricity prices.", "warning")
                self.mode = "mock"
            else:
                # get the raw price data from Amber
                amber_prices = self.get_prices()

                if not amber_prices:
                    self.logger.log_message("Failed to get Amber price information. Using mock mode for electricity prices.", "warning")
                    self.mode = "mock"
                else:
                    # Build the enriched price data array and truncate to only prices for today
                    self.prices = self.process_amber_prices(amber_prices)

                    # And the sorted version
                    self.prices_sorted = self.prices.copy()
                    self.prices_sorted.sort(key=operator.itemgetter("Price"))

        if self.mode == "mock":
            self.logger.log_message("Using mock prices for testing purposes.", "debug")
            self.prices = self.generate_mock_prices(average_price)
            self.prices_sorted = self.prices.copy()
            self.prices_sorted.sort(key=operator.itemgetter("Price"))

    def get_site_id(self) -> str | None:
        """Fetches the site ID from the Amber API.

        Logs a fatal error if there were no sites available or there was a problem with the API.
        Returns None if it appears that we have no internet connectivity.

        Returns:
            site_id (str | None): The site ID if found, otherwise None.
        """
        base_url = self.config.get("AmberAPI", "BaseUrl")
        if not base_url:
            self.logger.log_message("Amber API Base URL is not configured, cannot fetch Amber site ID.", "debug")
            return None

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.config.get('AmberAPI', 'APIKey')}",
        }
        try:
            url = base_url + "/sites"  # type: ignore[attr-defined]
            self.logger.log_message(f"Getting Amber site ID using API call: {url}", "debug")

            response = requests.get(f"{url}", headers=headers, timeout=self.config.get("AmberAPI", "Timeout", default=10))  # type: ignore[attr-defined]
            response.raise_for_status()
            sites = response.json()
            for site in sites:
                if site.get("status") == "active":
                    return site.get("id")

            self.logger.log_fatal_error("No active Amber sites found.")

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            self.logger.log_message(f"Connection error fetching Amber site ID at {url}: {e}", "warning")
            return None

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            self.logger.log_message(f"API timeout error fetching Amber site ID at {url}: {e}", "warning")
            return None

        except requests.exceptions.RequestException as e:
            self.logger.log_fatal_error(f"Error fetching Amber site ID: {e}")
            return None
        else:
            return None

    def get_prices(self) -> list[OrderedDict] | None:
        """Fetches the price forecast and saves the full JSON response.

        Returns:
            prices(list[OrderedDict]) | None: A list of ordered dictionaries containing the price data,
            or None if the site ID is not available.
        """
        if not self.site_id:
            self.logger.log_message("No site Amber ID available. Cannot fetch prices.", "error")
            return None

        self.logger.log_message("Downloading Amber prices for next 24 hours.", "summary")

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.config.get('AmberAPI', 'APIKey')}",
        }
        url = f"{self.config.get('AmberAPI', 'BaseUrl')}/sites/{self.site_id}/prices/current?next=47&previous=0&resolution=30"

        self.logger.log_message(f"Getting Amber prices using API call: {url}", "debug")

        try:
            response = requests.get(url, headers=headers, timeout=self.config.get("AmberAPI", "Timeout", default=10))  # type: ignore[attr-defined]
            response.raise_for_status()
            price_data = response.json()

        except requests.exceptions.ConnectionError as e:  # Trap connection error - ConnectionError
            self.logger.log_fatal_error(f"Connection error fetching Amber prices at {url}: {e}")

        except requests.exceptions.Timeout as e:  # Trap connection timeout error - ConnectTimeoutError
            self.logger.log_fatal_error(f"API timeout error fetching Amber prices at {url}: {e}")

        except requests.exceptions.RequestException as e:
            self.logger.log_fatal_error(f"Error fetching Amber prices: {e}")

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

        if self.config.get("Files", "LatestPriceData") is not None:
            lastest_price_data_path = SCCommon.select_file_location(self.config.get("Files", "LatestPriceData"))  # type: ignore[attr-defined]
            assert isinstance(lastest_price_data_path, Path)
            self.logger.log_message(f"Saving latest price data to {lastest_price_data_path}", "detailed")

            with lastest_price_data_path.open("w", encoding="utf-8") as json_file:
                json.dump(enhanced_data, json_file, indent=4)

        return enhanced_data

    def process_amber_prices(self, amber_prices: list[OrderedDict]) -> list[OrderedDict]:
        """
        Processes the enriched Amber price dictionary.

        Build our custom dictionary for prices in the required channel through to midnight.

        Args:
            amber_prices (list[OrderedDict]): The list of ordered dictionaries containing the Amber price data.

        Returns:
            return_prices(list[OrderedDict]): A fittered price list for today, or None if no price data is available.
        """
        return_prices = []
        slot = 0
        for amber_entry in amber_prices:
            # If we've moved into the next day, break
            entry_start_time = DateHelper.parse_date(amber_entry["localStartTime"], "%Y-%m-%dT%H:%M:%S")
            assert isinstance(entry_start_time, dt.datetime)
            # If the entry is for today and is the required channel, add it to the list
            if entry_start_time.date() == DateHelper.today() and amber_entry.get("channelType") == self.config.get("AmberAPI", "Channel"):
                price_entry = {
                    "Slot": slot,
                    "StartTime": amber_entry["localStartTime"].replace("T", " "),
                    "EndTime": amber_entry["localEndTime"].replace("T", " "),
                    "Price": amber_entry["perKwh"],
                    "Selected": None,
                }

                return_prices.append(price_entry)
                slot += 1

        if len(return_prices) == 0:
            self.logger.log_fatal_error(f"No Amber prices found for the {self.config.get('AmberAPI', 'Channel')} channel.")

        self.logger.log_message(f"{len(return_prices)} prices fetched successfully.", "debug")

        return return_prices

    @staticmethod
    def generate_mock_prices(average_price: float) -> list[OrderedDict]:
        """Generates mock prices for testing purposes.

        Args:
            average_price (float): The average price to use for mock prices

        Returns:
            mock_prices(list[OrderedDict]): A list of ordered dictionaries containing mock price data.
        """
        mock_prices = []

        # Get current time rounded down to nearest 30-minute slot
        now = DateHelper.now()
        rounded_minute = (now.minute // 30) * 30
        base_start_time = now.replace(minute=rounded_minute, second=1, microsecond=0)

        for i in range(48):
            # Generate a start time for each slot, starting from the rounded base time
            # and then incrementing by 30 minutes for each slot
            start_time = base_start_time + dt.timedelta(minutes=i * 30)

            # If start time date is after today, break out of the loop
            if start_time.date() > DateHelper.today():
                break
            end_time = start_time + dt.timedelta(minutes=30, seconds=-1)
            mock_prices.append(OrderedDict({
                "Slot": i,
                "StartTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "EndTime": end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "Price": average_price,
                "Selected": None,
            }))
        return mock_prices

    def get_current_price(self) -> float:
        """Fetches the current price from the Amber API.

        Returns:
            price(float): The current price in AUD/kWh.
        """
        return self.prices[0]["Price"] if len(self.prices) > 0 else 0

    def get_worst_price(self) -> float:
        """Fetches the worst price from the Amber API.

        Returns:
            price(float): The worst price in AUD/kWh.
        """
        return self.prices_sorted[-1]["Price"] if len(self.prices_sorted) > 0 else 0

    def have_live_prices(self) -> bool:
        """Checks if we have live prices available.

        Returns:
            bool: True if live prices are available, False otherwise.
        """
        return self.mode == "live"

    @staticmethod
    def convert_utc_dt_string(utc_time_str: str) -> str:
        """Converts a UTC datetime string to a local datetime string.

        Args:
            utc_time_str (str): The UTC datetime string in the format YYYY-MM-DDTH HH:MM:SSZ.

        Returns:
            local_time_str(str): The local datetime string in ISO format without microseconds.
        """
        # Parse the string into a datetime object (with UTC timezone)
        local_tz = dt.datetime.now().astimezone().tzinfo
        utc_dt = dt.datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).replace(tzinfo=None)

        # ZoneInfo() fails for my AEST timezone, so instead calculate the current time difference for UTC and local time
        local_timenow = dt.datetime.now(local_tz).replace(tzinfo=None)
        utc_timenow = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        tz_diff = local_timenow - utc_timenow + dt.timedelta(0, 1)

        # Convert to local time
        local_dt = utc_dt + tz_diff
        local_dt = local_dt.replace(microsecond=0)

        return local_dt.isoformat()
