# Overview
The Power Controller is a Python-based automation tool that schedules and controls a power load based on electricity pricing and user-configurable parameters. It integrates with the Amber API to fetch real-time electricity prices and optimizes the device operation to minimize costs while maintaining required run-time thresholds.
The Power Controller is currently designed for the following device types:
* Pool Pump: The goal is to run the pump for a target number of hours every day and for at least a minimum number of hours. The schedule is set so that pump runs at the cheapest times of day.
* Hot Water System: The heater element for an electric hot water heater. The goal is to keep power to the heater 24 hours a day except where the price exceeds a set price limit. 

# Features
* Dynamic Scheduling: Adjusts device operation based on real-time electricity prices.
* Configurable Parameters: Uses a YAML configuration file to set API credentials, run-time schedules, and file paths.
* Historical Tracking: Maintains past seven days of device runtime to optimize future scheduling.
* Logging: Saves run-time decisions and electricity prices to a CSV file.
* Automatic Configuration Handling: Creates a default configuration file if one does not exist.

# Installation & Setup
## Prerequisites
* Python 3.x installed:
macOS: `brew install python3`
Windows: `inget install python3 --source winget --scope machine`
* UV for Python installed:
macOS: 'brew install uvicorn'
Windows: ``pip install uv`

The shell script used to run the app (*launch.sh*) is uses the *uv sync* command to ensure that all the prerequitie Python packages are installed in the virtual environment.

## Running on Mac
If you're running the Python script on macOS, you need to allow the calling application (Terminal, Visual Studio) to access devices on the local network: *System Settings > Privacy and Security > Local Network*

# Configuration File 
The script uses the *config.yaml* YAML file for configuration. An example of included with the project (*config.yaml.example*). Copy this to *PowerControllerConfig.yaml* before running the app for the first time.  Here's an example config file:

    DeviceType:
        Type: PoolPump
        Label: Pool Pump
        WebsiteBaseURL: http://127.0.0.1:8000

    AmberAPI:
        APIKey: 123456789abc
        BaseUrl: https://api.amber.com.au/v1
        Channel: general
        Timeout: 10

    ShellySmartSwitch:
        Model: Shelly1PMG3
        IPAddress: 192.168.0.23
        SwitchID: 0
        DisableSwitch: False
        Timeout: 10

    DeviceRunScheule:
        MinimumRunHoursPerDay: 3
        MaximumRunHoursPerDay: 9
        TargetRunHoursPerDay: 6
        MaximumPriceToRun: 35
        ThresholdAboveCheapestPricesForMinumumHours: 1.1
        MonthlyTargetRunHoursPerDay:
            January: 9
            February: 9
        NoRunPeriods:
            - StartDate: "2025-05-07"
            EndDate: "2025-10-01"
            - StartDate: "2026-05-10"
            EndDate: "2026-10-01"  

    Files:
        SavedStateFile: PowerControllerState.json
        RunLogFile: PowerControllerRun.csv
        RunLogFileMaxLines: 500
        Logfile: PowerController.log
        LogfileMaxLines: 5000
        LogfileVerbosity: detailed
        ConsoleVerbosity: summary
        LatestPriceData: LatestAmberPrices.json

    Email:
        EnableEmail: True
        SendSummary: False
        DailyEnergyUseThreshold: 5000
        SMTPServer: smtp.gmail.com
        SMTPPort: 587
        SMTPUsername: me@gmail.com
        SMTPPassword: <Your SMTP password>

## Configuration Parameters
### Section: DeviceType

| Parameter | Description | 
|:--|:--|
| Type | What type of device are we controlling. Must be one of: *PoolPump* or *HotWaterSystem* |
| Label | The label (name) that for your device. |
| WebsiteBaseURL | If you have the PowerControllerUI web app installed and running (see page 11), then enter the URL for the home page here. Assuming this is on the same machine as the PowerController installation, this will typically be http://127.0.0.1:8000. The PowerController uses this URL to pass device state information to the web site. |

### Section: AmberAPI

| Parameter | Description | 
|:--|:--|
| APIKey | Your Amber API key for authentication. Login to  app.amber.com.au/developers/ and generate a new Token to get your API key.| 
| BaseUrl | Base URL for API requests. This the servers URL on the Amber developer's page, currently: https://api.amber.com.au/v1 |
| Channel | Which channel to we want to get the Amber prices for. By default, this should be *general*. If your device is connected to a controlled load meter, set this to *controlledLoad*. | 
| Timeout | Number of seconds to wait for Amber to respond to an API call | 

### Section: ShellySmartSwitch

| Parameter | Description | 
|:--|:--|
| Model | 	Which Shelly smart switch model are you using to control the load. Must be one of:<br>**ShellyEM**: Gen 1 Shelly energy meter with relay: To be used with an external contactor to switch the load and a 50A clamp to read energy use.<br>**ShellyPlus1PM**: Gen 2 Shelly 1PM switch with meter. This model has now been discontinued.<br>**Shelly1PMG3**: Gen 3 Shelly 1PM switch with meter. |
| IPAddress | The local IP address of your Shelly Smart Switch |
| SwitchID | If your smart switch has multiple relayed, the ID of the one to use. | 
| DisableSwitch | If set to True, this will prevent the Power Controller from actually changing the switch state. Used for testing.| 
| Timeout| Number of seconds to wait for the switch to respond to an API call | 

### Section: DeviceRunScheule

| Parameter | Description | 
|:--|:--|
| MinimumRunHoursPerDay | Minimum number of hours the pump must run daily.** | 
| MaximumRunHoursPerDay | Maximum allowed run-time per day.** | 
| TargetRunHoursPerDay | Desired daily average runtime over seven days.** | 
| MaximumPriceToRun | Never run the device if the c/kWh electricity price is greater than this, even if we haven't run for the minimum number of hours today.| 
| ThresholdAboveCheapestPricesForMinumumHours | If the device hasn't yet run for the minimum number of hours today, this parameter is used to determine whether the device should start now. The Power Controller looks at the prices for the time slots its plans to run on over rest of the day and takes the worst cheapest price from there. The device will only run now if the current price is less that the worst cheapest price factored by this parameter. | 
| MonthlyTargetRunHoursPerDay| Optionally override the TargetRunHoursPerDay setting for a specific month. See above for the example of  January and February.** | 
| NoRunPeriods | Optionally one or more StartDate / EndDate pairs that specify which dates the device should not run at all. Useful if the device is a hot water heater and you want to turn the power off while you are away. Dates must be entered as follows:<br>`- StartDate: "2025-05-07"`<br>&nbsp;&nbsp;&nbsp; `EndDate: "2025-10-01"`<br>`- StartDate: "2026-05-10"`<br>&nbsp;&nbsp;&nbsp; `EndDate: "2026-10-01"`  | 

**These parameters are ignored if the DeviceType is set to HotWaterSystem

### Section: Files

| Parameter | Description | 
|:--|:--|
| SavedStateFile | JSON file name to store the Power Controller's device current state and history. | 
| RunLogFile | Records a single status record each time the Power Controller script is run. If entry this is blank, this file won't be created.| 
| RunLogFileMaxLines | Maximum number of lines to keep in the RunLogFile. If zero, file will never be truncated. | 
| Logfile | A text log file that records progress messages and warnings. | 
| LogfileMaxLines| Maximum number of lines to keep in the log file. If zero, file will never be truncated. | 
| LogfileVerbosity | The level of detail captured in the log file. One of: none; error; warning; summary; detailed; debug; all | 
| ConsoleVerbosity | Controls the amount of information written to the console. One of: error; warning; summary; detailed; debug; all. Errors are written to stderr all other messages are written to stdout | 
| LatestPriceData | JSON file name storing latest price data fetched from the API. | 

### Section: Email

| Parameter | Description | 
|:--|:--|
| EnableEmail | Set to *True* if you want to allow the PowerController to send emails. If True, the remaining settings in this section must be configured correctly. | 
| SendSummary | If True, send a status summary email each time the PowerController runs. Useful to test that your email settings work. | 
| DailyEnergyUseThreshold | If the total energy used (in Watts) exceeds this amount for any one day, send a warning via email. This might indicate that the device is running longer than expected. Look at the EnergyUsed entries for the last 7 days in the PowerControllerState.json file for your average usage. Set to blank or 0 to disable. | 
| SMTPServer | The SMTP host name that supports TLS encryption. If using a Google account, set to smtp.gmail.com |
| SMTPPort | The port number to use to connect to the SMTP server. If using a Google account, set to 587 |
| SMTPUsername | Your username used to login to the SMTP server. If using a Google account, set to your Google email address. |
| SMTPPassword | The password used to login to the SMTP server. If using a Google account, create an app password for the PowerController at https://myaccount.google.com/apppasswords  |
| SubjectPrefix | Optional. If set, the PowerController will add this text to the start of any email subject line for emails it sends. |


# How It Works
## 1. Initialization:
* Loads the configuration from *config.yaml*. If the configuration file is missing, it generates a default one.
* Loads past runtime history from *PowerControllerState.json*.
* Fetches your site ID via the Amber API.

## 2. Fetching Price Data:
* Queries the Amber API to retrieve the current and forecast prices for the general channel for the next 24 hours in 30 minute time slots and this data to LatestAmberPrices.json.

## 3. Determining Device Schedule:
* The system calculates the current 30-minute slot based on the system time.
* Determines the cheapest slots for the rest of the day using the price data.
* Ensures the device runs at least the minimum required hours and does not exceed the maximum limit, selecting the cheapest slots to run on.
* Turns the device on or off as appropriate via a Shelly Smart Switch.
* Logs the device operation decision into the CSV file.
* Updates *PowerControllerState.json* to track daily runtime.

## 4. End-of-Day Update:
* At midnight, the script updates historical run-time data to maintain a rolling seven-day history.
* Resets today's runtime counter for the next day.

# Setting up the Smart Switch
The Power Controller is currently designed to physically start or stop the pool device via Shelly Smart Switch. This is a relay that can be connected to your local Wi-Fi network and controlled remotely via an API call. A detailed setup guide is beyond the scope of this document, but the brief steps are as follows:
* Purchase a Shelly Smart Switch. I used the [Shelly 1PM Gen3](https://www.shelly.com/products/shelly-1pm-gen3), available in Australia from [OzSmartThings](https://www.ozsmartthings.com.au/products/shelly-1-gen3). 
* Install the switch so that the relay output controls power to your device and chlorine generator. 
* 	Download the Shelly App from the app store (links on [this page](https://www.shelly.com/products/shelly-1pm-gen3)) and get the switch setup via the app so that you can turn the relay on and off via Wi-Fi (not Bluetooth).
* Update the *PowerControllerConfig.yaml* file and set the IPAddress setting in the ShellySmartSwitch section to the IP of your Shelly device. 
* If possible, create a DHCP reservation for the Shelly device in your local router so that the IP doesn't change.

# Running the Script
Execute the Python script using:

`launch.sh`

The script will fetch price data, determine the current time slot, decide whether to run the device, and log the action taken. If no valid price data is available, it will log an error.

# Web Interface 
There's a companion web app that can be used to monitor the Power Controller status. This is a simple web page that shows the current state of the device and the last 7 days of history. It can support multiple instances of the Power Controller running on different devices. 

Please see https://github.com/NickElseySpelloC/AmberPowerControllerUI for more information on how to install and run the web app.

# Logs and Data Files
The Power Controller will first look for these files in the current working directory and failing that, the same directory that the PowerController.py file exists in. If the Power Controller needs to create any of these files, it will do so in the PowerController.py folder.

* PowerControllerRun.csv: Logs each decision with the following information:
    * Current Time: The time the script was run 
    * Current Slot: The 30 minute slot as per the current time of day.
    * Required Slots: How many 30 minute slots do we need to run the device during the rest of the day to stay on schedule.
    * Current Price: the electricity price for the current slot. 
    * Average Forecast Price: The average price for all the 30 minute slots that the device will run for during the rest of the day.
    * Should Run: If TRUE, the device will be told to run until the next time this script is run.
    This name of this CSV is set via the RunLogFile configuration parameter.
* logfile.log: Progress messages and warnings are written to this file. The logging level is controlled by the LogfileVerbosity configuration parameter.
* LatestAmberPrices.json: Stores the latest electricity price data fetched from Amber API.
* PowerControllerState.json: Tracks past seven days of runtime and today's runtime.

# Troubleshooting
## "No module named xxx"
Ensure all the Python modules are installed in the virtual environment. Make sure you are running the PowerController via the *PowerController.sh* script.

## ModuleNotFoundError: No module named 'requests' (macOS)
If you can run the script just fine from the command line, but you're getting this error when running from crontab, make sure the crontab environment has the Python3 folder in it's path. First, at the command line find out where python3 is being run from:

`which python3`

And then add this to a PATH command in your crontab:

`PATH=/usr/local/bin:/usr/bin:/bin`
`0,15,30,45 * * * * /Users/bob/scripts/PowerController.sh `

## API Errors
If the script cannot fetch site IDs or prices, verify:
* The API key in PowerControllerConfig.yaml is correct.
* Amber API is reachable.
* The internet connection is active.

## Unexpected Behaviour
* Check *PowerControllerState.json* to ensure it is correctly storing data.
* Review *PowerControllerRun.csv* to see logged actions and pricing data.

# Appendix: PowerController State File
The *PowerControllerState.json* file holds the detailed state of the PowerController system. A new file will be created with default values the first time PowerController is run. 

You should never edit this file directly, but you can read the values from this file - for example to present in a web page. The structure is as follows:
* **MaxDailyRuntimeAllowed**: Maximum number of hours that the device can run on any day - we should  never exceed this. As per the MaximumRunHoursPerDay configuration parameter.
* **LastStateSaveTime**: Time this state was last written to file. 
* **LastRunSuccessful**: True if the last run completed successfully 
* **TotalRuntimePriorDays**: Total number of hours that we've run over the prior 7 days.
* **AverageRuntimePriorDays**: Average number of hours that we've run each day over the prior 7 days.
* **CurrentShortfall**: Cumulative shortfall runtime from the prior days 7 and today so far. 
* **ForecastRuntimeToday**: The number of hours that the device will actually run for the rest of today. This should ideally be the same as DailyData[0][RemainingRuntimeToday], but if the MaximumPriceToRun configuration setting it too low, the PowerController won't be able to find sufficient time slots to run in.
* **IsDeviceRunning**: Is the device currently running.
* **DeviceLastStartTime**: When the device was last turned on. None if not the device isn't currently running.
* **CurrentPrice**: Latest Amber price.
* **PriceTime**: Time that the latest Amber price was retrieved. 
* **EnergyAtLastStart**: The energy meter reading of the Shelly switch when the device was last started.
* **EnergyUsed**: Cumulative energy used in Watt-Hours for the prior 7 days and today.
* **TotalCost**: Total energy cost in cents for prior 7 days and today.
* **AveragePrice**: Average energy price (c/kWh) for the prior 7 days and today.
* **EarlierTotals**: Totals for all days more than 7 days prior to today.
    * **EnergyUsed**: Cumulative energy used in Watts.
    * **TotalCost**: Total cost in cents.
    * **RunTime**: How many hours has the device run for.
* **AlltimeTotals**: Totals for the all time including today.
    * **EnergyUsed**: Cumulative energy used in Watts.
    * **TotalCost**: Total cost in cents. 
    * **AveragePrice**: Average price (c/kWh). 
    * **RunTime**: How many hours has the device run for.
* **TodayRunPlan[]** An array time slots windows during which we plan to run the device for the rest of the day. Will be empty if there's nothing more to do today.
    * **ID**: Element index.
    * **From**: Start time for this window, rounded down to the nearest 30 minutes.
    * **To**: End time for this window, rounded up to the nearest 30 minutes.
    * **AveragePrice**: The average forecast price that we will pay for energy during this window. This assumes that the device's energy usage is consistent. 
* **AverageForecastPrice**: The average forecast price that we will pay for energy during all the time slots in today's run plan. 
* **TodayOriginalRunPlan[]**: This is a copy of the TodayRunPlan[] array taken before the first device run of the day.
* **DailyData[]**: An array of 8 elements representing the daily data for today and the 7 prior days.
    * **ID**: Day number with today being 0 and the day 7 days prior being 7. 
    * **Date**: The date of this day.
    * **RequiredDailyRuntime**: How many hours should we run each day. Taken from the configuration values TargetRunHoursPerDay and MonthlyTargetRunHoursPerDay.
    * **PriorShortfall**: Cumulative runtime shortfall (in hours) from the prior 7 days.
    * **TargetRuntime**: Our goal of how many hours we wish to run on this date, taking into account the prior shortfall, RequiredDailyRuntime, and the minimum and maximum number of hours we are allowed to run each day.
    * **RuntimeToday**: How many hours did we run this day.
    * **RemainingRuntimeToday**: How many more hours do we have to run on this day. 
    * **EnergyUsed**: Total energy used in Watt-Hours on this day.
    * **AveragePrice**: Average price paid for all the eneregy used on this day.
    * **TotalCost**: Total cost in cents paid for eneregy used on this day.
    * **DeviceRuns[]**: Array of device runs. Each run logs the time when the device was switched on during this day.
        * **ID**: The run number, starting at 0.
        * **StartTme**: Time that device was started.
        * **RunTime**: How long the device run for in hours. None if still running.
        * **EndTime**: Time that device was stopped. None if still running.
        * **EnergyUsedStart**: The Shelly switch energy meter reading when this run started.
        * **EnergyUsedForRun**: The total energy used for this run. None if still running.
        * **Price**: Price in cents for when device was started.
        * **Cost**: Total cost in cents for this run. None if still running.
