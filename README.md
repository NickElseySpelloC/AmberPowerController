# Amber Power Controller Overview
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
* Optionally integrate with the [PowerControllerViewer app](https://github.com/NickElseySpelloC/PowerControllerViewer) so that yu can view light status, schedules and history via a web interface.
* Email notification for critical errors.
* Integration with the BetterStack uptime for heatbeat monitoring

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
The script uses the *config.yaml* YAML file for configuration. An example of included with the project (*config.yaml.example*). Copy this to *config.yaml* before running the app for the first time.  Here's an example config file:

```yaml
DeviceType:
  # Set this to the type of device you are controlling. One of: 
  #   PoolPump
  #   HotWaterSystem
  Type: PoolPump
  # The Shelly smart switch to turn the pump on and off. Enter a name or ID that matches a ShellyDevices: Devices: Outputs section below.
  Switch: "Pool Switch 1"
  # The Shelly smart switch emeter to monitor energy use. Can be blank. Enter a name or ID that matches a ShellyDevices: Devices: Meters section below.
  Meter: "Pool Meter 1"  
  # The name for your device, used in the web app and logs
  Label: iMac Pool Pump
  # Set this to the homepage URL of the PowerControllerViewer web app. This URL is used to transfer device status to the website.
  WebsiteBaseURL: http://127.0.0.1:8000
  WebsiteAccessKey: <Your website API key here>

AmberAPI:
  # Set this to the API key for your account - get this at app.amber.com.au/developers/
  APIKey: <Your Amber API key here>
  BaseUrl: https://api.amber.com.au/v1
  # Which channel do we get the price data for - one of general or controlledLoad
  Channel: general
  Timeout: 15

# Settings for the Shelly Plus smart switch, used switch power to your device
  ShellyDevices:
    ResponseTimeout: 3
    RetryCount: 1
    RetryDelay: 2
    PingAllowed: True
    Devices:
      - Name: Shelly Pool
        Model: Shelly2PMG3
        Hostname: 192.168.1.25
        Simulate: False
        Outputs:
          - Name: "Pool Switch 1"
          - Name: "Pool Switch 2"
        Meters:
          - Name: "Pool Meter 1"
          - Name: "Pool Meter 2"
      - Name: Mock Switch
        Model: ShellyPlus1PM
        Simulate: True
        Outputs:
            - Name: "Mock Switch 1"
        Meters:
            - Name: "Mock Meter 1" 


# Your desired settings for the pump's runtime. See the documentation for details.
# If the device type is HotWaterSystem then only the MaximumPriceToRun and 
# ThresholdAboveCheapestPricesForMinumumHours parameters are used.
DeviceRunScheule:
  MinimumRunHoursPerDay: 2
  MaximumRunHoursPerDay: 10
  TargetRunHoursPerDay: 7
  MaximumPriceToRun: 20
  ThresholdAboveCheapestPricesForMinumumHours: 1.1
  # The times of day when the device should run. This is used when the Amber pricing API is not available or you want o manually control the device.
  # Set the manual schedule hours to be longer than your TargetRunHoursPerDay and app will automatically adjust the run time to match the TargetRunHoursPerDay.
  # Specify the StartTime and EndTime in 24-hour format (HH:MM) - for example, "08:00" for 8 AM and "16:00" for 4 PM.
  ManualSchedule:
    - StartTime: "11:00"
      EndTime: "16:00"
    - StartTime: "20:00"
      EndTime: "23:00"  # Optionally override the monthly target run hours per day
  MonthlyTargetRunHoursPerDay:
    January: 8
    February: 8
    June: 6
    July: 6
    August: 6
    December: 8
  # Specify date ranges when the device should not run
  NoRunPeriods:
    - StartDate: "2025-09-01"
      EndDate: "2025-09-20"
    - StartDate: "2025-12-28"
      EndDate: "2026-12-31"  

Files:
  # The name of the saved state file. This is used to store the state of the device between runs.
  SavedStateFile:  system_state.json
  # Optional name of a CSV to log the device state and current price to after each run
  LogfileName: logfile.log
  LogfileMaxLines: 5000
  # How much information do we write to the log file. One of: none; error; warning; summary; detailed; debug
  LogfileVerbosity: debug
  # How much information do we write to the console. One of: error; warning; summary; detailed; debug
  ConsoleVerbosity: detailed
  # How much information do we write to the log file. One of: none; error; warning; summary; detailed; debug
  LatestPriceData: 
  # Optionally save the daily run stats to a CSV file
  DailyRunStatsCSV: daily_run_stats.csv
  # Number of days to keep the daily run stats CSV file
  DailyRunStatsDaysToKeep: 365

# Enter your settings here if you want to be emailed when there's a critical error 
Email:
  EnableEmail: True
  SendSummary: False
  DailyEnergyUseThreshold: 6000
  SendEmailsTo: <Your email address here>
  SMTPServer: <Your SMTP server here>
  SMTPPort: 587
  SMTPUsername: <Your SMTP username here>
  SMTPPassword: <Your SMTP password here>
  SubjectPrefix: 

HeartbeatMonitor:
  # Optionally, the URL of the website to monitor for availability
  WebsiteURL: https://uptime.betterstack.com/api/v1/heartbeat/myheartbeatid
  # How long to wait for a response from the website before considering it down in seconds
  HeartbeatTimeout: 5  
```

## Configuration Parameters
### Section: DeviceType

| Parameter | Description | 
|:--|:--|
| Type | What type of device are we controlling. Must be one of: *PoolPump* or *HotWaterSystem* |
| Switch | The Shelly smart switch to turn the pump on and off. Enter a name or ID that matches a ShellyDevices: Devices: Outputs section below. |
| Meter | The Shelly smart switch emeter to monitor energy use. Can be blank. Enter a name or ID that matches a ShellyDevices: Devices: Meters section below. |
| Label | The label (name) that for your device. |
| WebsiteBaseURL | If you have the PowerControllerViewer web app installed and running (see page 11), then enter the URL for the home page here. Assuming this is on the same machine as the AmberPowerController installation, this will typically be http://127.0.0.1:8000. The AmberPowerController uses this URL to pass device state information to the web site. |
| WebsiteAccessKey | If you have configured an access key for the PowerControllerViewer, configure it here.  |
| WebsiteTimeout | How long to wait for a reponse from the PowerControllerViewer when posting state information. |

### Section: AmberAPI

| Parameter | Description | 
|:--|:--|
| APIKey | Your Amber API key for authentication. Login to  app.amber.com.au/developers/ and generate a new Token to get your API key.| 
| BaseUrl | Base URL for API requests. This the servers URL on the Amber developer's page, currently: https://api.amber.com.au/v1 |
| Channel | Which channel to we want to get the Amber prices for. By default, this should be *general*. If your device is connected to a controlled load meter, set this to *controlledLoad*. | 
| Timeout | Number of seconds to wait for Amber to respond to an API call | 

### Section: ShellyDevices

In this section you can configure one or more Shelly Smart switches, one of which will be used to contro your pool pump or water heater and optionally monitor its energy usage. See the [Shelly Getting Started guide](https://nickelseyspelloc.github.io/sc_utility/guide/shelly_control/) for details on how to configure this section.

### Section: DeviceRunScheule

| Parameter | Description | 
|:--|:--|
| MinimumRunHoursPerDay | Minimum number of hours the pump must run daily.** | 
| MaximumRunHoursPerDay | Maximum allowed run-time per day.** | 
| TargetRunHoursPerDay | Desired daily average runtime over seven days.** | 
| MaximumPriceToRun | Never run the device if the c/kWh electricity price is greater than this, even if we haven't run for the minimum number of hours today.| 
| ThresholdAboveCheapestPricesForMinumumHours | If the device hasn't yet run for the minimum number of hours today, this parameter is used to determine whether the device should start now. The Power Controller looks at the prices for the time slots its plans to run on over rest of the day and takes the worst cheapest price from there. The device will only run now if the current price is less that the worst cheapest price factored by this parameter. | 
| ManualSchedule | The times of day when the device should run. This is used when the Amber pricing API is not available or you want to manually control the device. Set the manual schedule hours to be longer than your TargetRunHoursPerDay and app will automatically adjust the run time to match the TargetRunHoursPerDay. Specify the StartTime and EndTime in 24-hour format (HH:MM) - for example, "08:00" for 8 AM and "16:00" for 4 PM. |
| MonthlyTargetRunHoursPerDay| Optionally override the TargetRunHoursPerDay setting for a specific month. See above for the example of  January and February.** | 
| NoRunPeriods | Optionally one or more StartDate / EndDate pairs that specify which dates the device should not run at all. Useful if the device is a hot water heater and you want to turn the power off while you are away. Dates must be entered as follows:<br>`- StartDate: "2025-05-07"`<br>&nbsp;&nbsp;&nbsp; `EndDate: "2025-10-01"`<br>`- StartDate: "2026-05-10"`<br>&nbsp;&nbsp;&nbsp; `EndDate: "2026-10-01"`  | 

**These parameters are ignored if the DeviceType is set to HotWaterSystem

### Section: Files

| Parameter | Description | 
|:--|:--|
| SavedStateFile | JSON file name to store the Power Controller's device current state and history. | 
| Logfile | A text log file that records progress messages and warnings. | 
| LogfileMaxLines| Maximum number of lines to keep in the log file. If zero, file will never be truncated. | 
| LogfileVerbosity | The level of detail captured in the log file. One of: none; error; warning; summary; detailed; debug; all | 
| ConsoleVerbosity | Controls the amount of information written to the console. One of: error; warning; summary; detailed; debug; all. Errors are written to stderr all other messages are written to stdout | 
| LatestPriceData | JSON file name storing latest price data fetched from the API. | 
| DailyRunStatsCSV | Optionally save the daily run stats to a CSV file.| 
| DailyRunStatsDaysToKeep | Number of days to keep the daily run stats CSV file. | 

### Section: Email

| Parameter | Description | 
|:--|:--|
| EnableEmail | Set to *True* if you want to allow the AmberPowerController to send emails. If True, the remaining settings in this section must be configured correctly. | 
| SendSummary | If True, send a status summary email each time the AmberPowerController runs. Useful to test that your email settings work. | 
| DailyEnergyUseThreshold | If the total energy used (in Watts) exceeds this amount for any one day, send a warning via email. This might indicate that the device is running longer than expected. Look at the EnergyUsed entries for the last 7 days in the system_state.json file for your average usage. Set to blank or 0 to disable. | 
| SMTPServer | The SMTP host name that supports TLS encryption. If using a Google account, set to smtp.gmail.com |
| SMTPPort | The port number to use to connect to the SMTP server. If using a Google account, set to 587 |
| SMTPUsername | Your username used to login to the SMTP server. If using a Google account, set to your Google email address. |
| SMTPPassword | The password used to login to the SMTP server. If using a Google account, create an app password for the AmberPowerController at https://myaccount.google.com/apppasswords  |
| SubjectPrefix | Optional. If set, the AmberPowerController will add this text to the start of any email subject line for emails it sends. |

### Section: HeartbeatMonitor

| Parameter | Description | 
|:--|:--|
| WebsiteURL | Each time the app runs successfully, you can have it hit this URL to record a heartbeat. This is optional. If the app exist with a fatal error, it will append /fail to this URL. | 
| HeartbeatTimeout | How long to wait for a response from the website before considering it down in seconds. | 


# How It Works
## 1. Initialization:
* Loads the configuration from *config.yaml*. If the configuration file is missing, it generates a default one.
* Loads past runtime history from *system_state.json*.
* Fetches your site ID via the Amber API.

## 2. Fetching Price Data:
* Queries the Amber API to retrieve the current and forecast prices for the general channel for the next 24 hours in 30 minute time slots and this data to LatestAmberPrices.json.

## 3. Determining Device Schedule:
* The system calculates the current 30-minute slot based on the system time.
* Determines the cheapest slots for the rest of the day using the price data.
* Ensures the device runs at least the minimum required hours and does not exceed the maximum limit, selecting the cheapest slots to run on.
* Turns the device on or off as appropriate via a Shelly Smart Switch.
* Logs the device operation decision into the CSV file.
* Updates *system_state.json* to track daily runtime.

## 4. End-of-Day Update:
* At midnight, the script updates historical run-time data to maintain a rolling seven-day history.
* Resets today's runtime counter for the next day.

# Setting up the Smart Switch
The Power Controller is currently designed to physically start or stop the pool device via Shelly Smart Switch. This is a relay that can be connected to your local Wi-Fi network and controlled remotely via an API call. A detailed setup guide is beyond the scope of this document, but the brief steps are as follows:
* Purchase a Shelly Smart Switch. See the [Models Library](https://nickelseyspelloc.github.io/sc_utility/guide/shelly_models_list/) for a list of supported models and which of these have an energy meter built in.
* Install the switch so that the relay output controls power to your device. 
* Download the Shelly App from the app store (links on [this page](https://www.shelly.com/pages/shelly-app)) and get the switch setup via the app so that you can turn the relay on and off via Wi-Fi (not Bluetooth).
* Update the ShellyDevices section of your *config.yaml* file. 
* If possible, create a DHCP reservation for the Shelly device in your local router so that the IP doesn't change.

# Running the Script
Execute the Python script using:

```bash
launch.sh
```

The script will fetch price data, determine the current time slot, decide whether to run the device, and log the action taken. If no valid price data is available, it will log an error.

# Web Interface 
There's a companion web app that can be used to monitor the Power Controller status. This is a simple web page that shows the current state of the device and the last 7 days of history. It can support multiple instances of the Power Controller running on different devices. 

Please see https://github.com/NickElseySpelloC/PowerControllerViewer for more information on how to install and run the web app.

# Logs and Data Files
The Power Controller will first look for these files in the current working directory and failing that, the same directory that the main.py file exists in. If the Power Controller needs to create any of these files, it will do so in the main.py folder.

* daily_run_stats.csv: Logs key metrics for each day's run.
* logfile.log: Progress messages and warnings are written to this file. The logging level is controlled by the LogfileVerbosity configuration parameter.
* latest_prices.json: Stores the latest electricity price data fetched from Amber API (if configured)
* system_state.json: Tracks past seven days of runtime and today's runtime. Please don't modify this file.

# Troubleshooting
## "No module named xxx"
Ensure all the Python modules are installed in the virtual environment. Make sure you are running the AmberPowerController via the *launch.sh* script.

## ModuleNotFoundError: No module named 'requests' (macOS)
If you can run the script just fine from the command line, but you're getting this error when running from crontab, make sure the crontab environment has the Python3 folder in it's path. First, at the command line find out where python3 is being run from:

`which python3`

And then add this to a PATH command in your crontab:

`PATH=/usr/local/bin:/usr/bin:/bin:/sbin`
`0,15,30,45 * * * * /Users/bob/scripts/Launch.sh `

## API Errors
If the script cannot fetch site IDs or prices, verify:
* The API key in Config.yaml is correct.
* Amber API is reachable.
* The internet connection is active.

## Unexpected Behaviour
* Check *system_state.json* to ensure it is correctly storing data.

# Appendix: system_state State File
The *system_state.json* file holds the detailed state of the AmberPowerController system. A new file will be created with default values the first time AmberPowerController is run. 