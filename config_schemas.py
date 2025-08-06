"""Configuration schemas for use with the SCConfigManager class."""


class ConfigSchema:
    """Base class for configuration schemas."""

    def __init__(self):
        self.default = {
            "DeviceType": {
                "Type": "PoolPump",
                "Label": "Pool Pump",
                "WebsiteBaseURL": None,
                "WebsiteAccessKey": "<Your website API key here>",
                "WebsiteTimeout": 5,
            },
            "AmberAPI": {
                "APIKey": "<Your API Key Here>",
                "BaseUrl": "https://api.amber.com.au/v1",
                "Channel": "general",
                "Timeout": 10,
            },
            "ShellyDevices": {
                "Devices": [
                    {
                        "Name": "Shelly 1",
                        "Model": "Shelly2PMG3",
                        "Hostname": "<Your Shelly device hostname here>",
                        "Simulate": False,
                        "Inputs": [
                            {"Name": "Input 1", "ID": 0},
                            {"Name": "Input 2", "ID": 1},
                        ],
                        "Outputs": [
                            {"Name": "Switch 1", "ID": 0},
                            {"Name": "Switch 1", "ID": 1},
                        ],
                        "Meters": [
                            {"Name": "Meter 1", "ID": 0},
                            {"Name": "Meter 2", "ID": 1},
                        ],
                    }
                ],
            },
            "DeviceRunScheule": {
                "MinimumRunHoursPerDay": 3,
                "MaximumRunHoursPerDay": 9,
                "TargetRunHoursPerDay": 6,
                "MaximumPriceToRun": 20,
                "ThresholdAboveCheapestPricesForMinumumHours": 1.1,
            },
            "Files": {
                "SavedStateFile": "system_state.json",
                "LogfileName": "logfile.log",
                "LogfileMaxLines": 5000,
                "LogfileVerbosity": "summary",
                "ConsoleVerbosity": "summary",
                "LatestPriceData": "Amber_prices.json",
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
                "SubjectPrefix": None,
            },
        }

        self.placeholders = {
            "DeviceType": {
                "WebsiteAccessKey": "<Your website API key here>",
            },
            "AmberAPI": {
                "APIKey": "<Your API Key Here>",
            },
            "Email": {
                "SMTPUsername": "<Your SMTP username here>",
                "SMTPPassword": "<Your SMTP password here>",
            }
        }

        self.validation = {
            "DeviceType": {
                "type": "dict",
                "schema": {
                    "Type": {"type": "string", "required": True, "allowed": ["PoolPump", "HotWaterSystem"]},
                    "Label": {"type": "string", "required": True},
                    "Switch": {"type": ("string", "number"), "required": True},
                    "Meter": {"type": ("string", "number"), "required": False, "nullable": True},
                    "WebsiteBaseURL": {"type": "string", "required": False, "nullable": True},
                    "WebsiteAccessKey": {"type": "string", "required": False, "nullable": True},
                    "WebsiteTimeout": {"type": "number", "required": False, "nullable": True},
                },
            },
            "AmberAPI": {
                "type": "dict",
                "schema": {
                    "APIKey": {"type": "string", "required": False, "nullable": True},
                    "BaseUrl": {"type": "string", "required": False, "nullable": True},
                    "Channel": {"type": "string", "required": False, "nullable": True, "allowed": ["general", "controlledLoad"]},
                    "Timeout": {"type": "number", "required": False, "nullable": True, "min": 5, "max": 60},
                },
            },
            "ShellyDevices": {
                "type": "dict",
                "schema": {
                    "ResponseTimeout": {"type": "number", "required": False, "nullable": True, "min": 1, "max": 120},
                    "RetryCount": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 10},
                    "RetryDelay": {"type": "number", "required": False, "nullable": True, "min": 1, "max": 10},
                    "PingAllowed": {"type": "boolean", "required": False, "nullable": True},
                    "Devices": {
                        "type": "list",
                        "required": True,
                        "nullable": False,
                        "schema": {
                            "type": "dict",
                            "schema": {
                                "Name": {"type": "string", "required": False, "nullable": True},
                                "Model": {"type": "string", "required": True},
                                "Hostname": {"type": "string", "required": False, "nullable": True},
                                "Port": {"type": "number", "required": False, "nullable": True},
                                "ID": {"type": "number", "required": False, "nullable": True},
                                "Simulate": {"type": "boolean", "required": False, "nullable": True},
                                "Inputs": {
                                    "type": "list",
                                    "required": False,
                                    "nullable": True,
                                    "schema": {
                                        "type": "dict",
                                        "schema": {
                                            "Name": {"type": "string", "required": False, "nullable": True},
                                            "ID": {"type": "number", "required": False, "nullable": True},
                                        },
                                    },
                                },
                                "Outputs": {
                                    "type": "list",
                                    "required": False,
                                    "nullable": True,
                                    "schema": {
                                        "type": "dict",
                                        "schema": {
                                            "Name": {"type": "string", "required": False, "nullable": True},
                                            "Group": {"type": "string", "required": False, "nullable": True},
                                            "ID": {"type": "number", "required": False, "nullable": True},
                                        },
                                    },
                                },
                                "Meters": {
                                    "type": "list",
                                    "required": False,
                                    "nullable": True,
                                    "schema": {
                                        "type": "dict",
                                        "schema": {
                                            "Name": {"type": "string", "required": False, "nullable": True},
                                            "ID": {"type": "number", "required": False, "nullable": True},
                                        },
                                    },
                                },
                            },
                        },
                    },
                }
            },
            "DeviceRunScheule": {
                "type": "dict",
                "schema": {
                    "MinimumRunHoursPerDay": {"type": "number", "required": True, "min": 1, "max": 12},
                    "MaximumRunHoursPerDay": {"type": "number", "required": True, "min": 2, "max": 20},
                    "TargetRunHoursPerDay": {"type": "number", "required": True, "min": 2, "max": 20},
                    "MaximumPriceToRun": {"type": "number", "required": True, "min": 10, "max": 500},
                    "ThresholdAboveCheapestPricesForMinumumHours": {"type": "number", "required": False, "nullable": True, "min": 1.0, "max": 2.0},
                    "ManualSchedule": {
                        "type": "list",
                        "required": False,
                        "nullable": True,
                        "schema": {
                            "type": "dict",
                            "schema": {
                                "StartTime": {"type": "string", "required": False, "nullable": True},
                                "EndTime": {"type": "string", "required": False, "nullable": True},
                            },
                        },
                    },
                    "MonthlyTargetRunHoursPerDay": {"type": "dict", "required": False, "nullable": True},
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
                                    "regex": r"^\d{4}-\d{2}-\d{2}$",  # Validates the format YYYY-MM-DD
                                },
                                "EndDate": {
                                    "type": "string",
                                    "required": False,
                                    "regex": r"^\d{4}-\d{2}-\d{2}$",  # Validates the format YYYY-MM-DD
                                },
                            },
                        },
                    },
                },
            },
            "Files": {
                "type": "dict",
                "schema": {
                    "SavedStateFile": {"type": "string", "required": True},
                    "LogfileName": {"type": "string", "required": False, "nullable": True},
                    "LogfileMaxLines": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100000},
                    "LogfileVerbosity": {"type": "string", "required": True, "allowed": ["none", "error", "warning", "summary", "detailed", "debug", "all"]},
                    "ConsoleVerbosity": {"type": "string", "required": True, "allowed": ["error", "warning", "summary", "detailed", "debug"]},
                    "LatestPriceData": {"type": "string", "required": False, "nullable": True},
                    "DailyRunStatsCSV": {"type": "string", "required": False, "nullable": True},
                    "DailyRunStatsDaysToKeep": {"type": "number", "required": False, "nullable": True, "min": 2},
                },
            },
            "Email": {
                "type": "dict",
                "schema": {
                    "EnableEmail": {"type": "boolean", "required": False, "nullable": True},
                    "SendSummary": {"type": "boolean", "required": False, "nullable": True},
                    "DailyEnergyUseThreshold": {"type": "number", "required": False, "nullable": True, "min": 1000, "max": 25000},
                    "SendEmailsTo": {"type": "string", "required": False, "nullable": True},
                    "SMTPServer":  {"type": "string", "required": False, "nullable": True},
                    "SMTPPort": {"type": "number", "required": False, "nullable": True, "min": 25, "max": 10000},
                    "SMTPUsername": {"type": "string", "required": False, "nullable": True},
                    "SMTPPassword": {"type": "string", "required": False, "nullable": True},
                    "SubjectPrefix": {"type": "string", "required": False, "nullable": True},
                },
            },
            "HeartbeatMonitor": {
                "type": "dict",
                "schema": {
                    "WebsiteURL": {"type": "string", "required": False, "nullable": True},
                    "HeartbeatTimeout": {"type": "number", "required": False, "nullable": True, "min": 1, "max": 60},
                },
            },
        }

        self.csv_header_config = [
            {
                "name": "Date",
                "type": "date",
                "format": "%Y-%m-%d",
                "match": True,
                "sort": 1,
                "minimum": None,
            },
            {
                "name": "DeviceName",
                "type": "str",
            },
            {
                "name": "CurrentState",
                "type": "str",
            },
            {
                "name": "TargetRuntime",
                "type": "float",
                "format": ".1f",
            },
            {
                "name": "RuntimeToday",
                "type": "float",
                "format": ".1f",
            },
            {
                "name": "RemainingRuntimeToday",
                "type": "float",
                "format": ".1f",
            },
            {
                "name": "EnergyUsage",
                "type": "float",
                "format": ".2f",
            },
            {
                "name": "EnergyCost",
                "type": "float",
                "format": ".2f",
            },
            {
                "name": "AveragePrice",
                "type": "float",
                "format": ".2f",
            },
        ]
